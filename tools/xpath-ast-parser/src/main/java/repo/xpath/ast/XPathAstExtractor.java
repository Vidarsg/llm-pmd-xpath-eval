package repo.xpath.ast;

import java.lang.reflect.Array;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Converts one JSON row containing a PMD XPath expression into a normalized AST
 * record.
 *
 * <p>Saxon performs the actual XPath parsing. This class adapts Saxon's
 * internal expression objects into a small, stable AST shape used by the
 * project's structural-similarity analysis.</p>
 */
public final class XPathAstExtractor {
    /** Input metadata preserved next to parse results for later aggregation. */
    private static final List<String> PASSTHROUGH_KEYS = Arrays.asList(
            "model", "promptStyle", "target", "temperature", "runCount"
    );

    /** Parses the row's XPath and returns a record that always includes status. */
    public AstRecord extract(Map<String, Object> row) {
        AstRecord record = new AstRecord();
        record.ruleKey = row.get("ruleKey");
        record.xpath = stringValue(row.get("xpath"));
        for (String key : PASSTHROUGH_KEYS) {
            if (row.containsKey(key)) {
                record.passthrough.put(key, row.get(key));
            }
        }

        try {
            Object expression = parseXPath(record.xpath);
            record.ast = toAst(expression);
            record.parseSuccess = true;
            record.parseError = null;
        } catch (Exception e) {
            record.ast = null;
            record.parseSuccess = false;
            record.parseError = rootCauseMessage(e);
        }
        return record;
    }

    /**
     * Uses Saxon to parse XPath into an internal expression tree.
     *
     * <p>The reflective ExpressionTool.make lookup keeps the tool tolerant of
     * small Saxon API signature changes across versions.</p>
     */
    private Object parseXPath(String xpath) throws Exception {
        net.sf.saxon.Configuration configuration = new net.sf.saxon.Configuration();
        PmdExtensionFunctions.registerAll(configuration);

        Object staticContext = buildStaticContext(configuration);
        declareNamespace(staticContext, "pmd", "urn:pmd");
        declareNamespace(staticContext, "pmd-java", "urn:pmd-java");

        Class<?> expressionToolClass = Class.forName("net.sf.saxon.expr.parser.ExpressionTool");
        for (Method method : expressionToolClass.getMethods()) {
            if (!method.getName().equals("make")) {
                continue;
            }
            try {
                Object[] args = buildExpressionToolArgs(method.getParameterTypes(), xpath, staticContext);
                if (args != null) {
                    return method.invoke(null, args);
                }
            } catch (InvocationTargetException e) {
                throw unwrap(e);
            }
        }

        throw new IllegalStateException("Could not find a compatible Saxon ExpressionTool.make(...) signature");
    }

    /** Creates the static context that holds namespace and extension metadata. */
    private Object buildStaticContext(Object configuration) {
        return new net.sf.saxon.sxpath.IndependentContext((net.sf.saxon.Configuration) configuration);
    }

    /**
     * Declares a namespace while handling Saxon versions that use different
     * declareNamespace signatures.
     */
    private void declareNamespace(Object staticContext, String prefix, String uri) {
        try {
            try {
                Method legacyMethod = staticContext.getClass().getMethod("declareNamespace", String.class, String.class);
                legacyMethod.invoke(staticContext, prefix, uri);
                return;
            } catch (NoSuchMethodException ignored) {
                // Saxon 12 uses NamespaceUri instead of String.
            }

            Class<?> namespaceUriClass = Class.forName("net.sf.saxon.om.NamespaceUri");
            Method ofMethod = namespaceUriClass.getMethod("of", String.class);
            Object namespaceUri = ofMethod.invoke(null, uri);
            Method method = staticContext.getClass().getMethod("declareNamespace", String.class, namespaceUriClass);
            method.invoke(staticContext, prefix, namespaceUri);
        } catch (Exception ignored) {
            // Namespace declaration is required for PMD-prefixed functions, but some Saxon context variants may still differ.
        }
    }

    /**
     * Builds arguments for whichever ExpressionTool.make overload is available.
     */
    private Object[] buildExpressionToolArgs(Class<?>[] parameterTypes, String xpath, Object staticContext) {
        Object[] args = new Object[parameterTypes.length];
        boolean usedString = false;
        boolean usedContext = false;

        for (int i = 0; i < parameterTypes.length; i++) {
            Class<?> type = parameterTypes[i];
            String name = type.getName();
            if (!usedString && type == String.class) {
                args[i] = xpath;
                usedString = true;
            } else if (!usedContext && type.isInstance(staticContext)) {
                args[i] = staticContext;
                usedContext = true;
            } else if (!usedContext && type.isAssignableFrom(staticContext.getClass())) {
                args[i] = staticContext;
                usedContext = true;
            } else if (type == int.class || type == Integer.TYPE) {
                args[i] = 0;
            } else if (type == boolean.class || type == Boolean.TYPE) {
                args[i] = Boolean.FALSE;
            } else if ("net.sf.saxon.expr.parser.CodeInjector".equals(name)) {
                args[i] = null;
            } else if ("net.sf.saxon.expr.StaticContext".equals(name)
                    || "net.sf.saxon.expr.parser.RetainedStaticContext".equals(name)
                    || "net.sf.saxon.sxpath.IndependentContext".equals(name)) {
                args[i] = staticContext;
                usedContext = true;
            } else {
                return null;
            }
        }

        return usedString && usedContext ? args : null;
    }

    /** Recursively normalizes a Saxon expression object into the output AST. */
    private AstNode toAst(Object expression) throws Exception {
        expression = unwrapExpression(expression);
        AstNode node = new AstNode(normalizeKind(expression));
        node.name = extractName(expression);
        node.operator = extractOperator(expression);
        node.valueType = extractValueType(expression);
        node.value = extractLiteralValue(expression);

        for (Object childExpression : childExpressions(expression)) {
            node.children.add(toAst(childExpression));
        }
        return node;
    }

    /**
     * Removes Saxon wrapper nodes that do not add useful structure for the
     * comparison metric.
     */
    private Object unwrapExpression(Object expression) throws Exception {
        String simpleName = expression.getClass().getSimpleName();
        if ("HomogeneityChecker".equals(simpleName)) {
            List<Object> children = childExpressions(expression);
            if (children.size() == 1) {
                return unwrapExpression(children.get(0));
            }
        }
        return expression;
    }

    /** Maps Saxon implementation class names to a smaller, parser-independent vocabulary. */
    private String normalizeKind(Object expression) {
        String simpleName = expression.getClass().getSimpleName();
        String lower = simpleName.toLowerCase(Locale.ROOT);

        if (lower.contains("root")) return "Root";
        if (lower.contains("axis")) return "AxisStep";
        if (lower.contains("function")) return "FunctionCall";
        if (lower.contains("literal")) return "Literal";
        if (lower.contains("variable")) return "VariableRef";
        if (lower.contains("filter") || lower.contains("predicate")) return "Predicate";
        if (lower.contains("slash") || lower.contains("path")) return "PathExpr";
        if (lower.contains("binary") || lower.contains("compare") || lower.contains("boolean") || lower.contains("venn")) return "BinaryOp";
        if (lower.contains("unary") || lower.contains("negate")) return "UnaryOp";
        return simpleName;
    }

    /** Extracts the most useful stable name Saxon exposes for an expression. */
    private String extractName(Object expression) throws Exception {
        String kind = normalizeKind(expression);
        for (String methodName : new String[]{
                "getFunctionName", "getEQName", "getDisplayName", "getExpressionName", "toShortString"
        }) {
            Object value = invokeNoArgIfPresent(expression, methodName);
            String normalized = normalizeNamedValue(value);
            if (isUsefulName(normalized)) {
                return normalized;
            }
        }

        Object targetFunction = invokeNoArgIfPresent(expression, "getTargetFunction");
        String targetFunctionName = normalizeNamedValue(targetFunction);
        if (isUsefulName(targetFunctionName)) {
            return targetFunctionName;
        }

        Object nodeTest = invokeNoArgIfPresent(expression, "getNodeTest");
        String nodeTestName = normalizeNamedValue(nodeTest);
        if (isUsefulName(nodeTestName)) {
            return nodeTestName;
        }

        return genericNameForKind(kind);
    }

    /** Extracts a readable operator marker where Saxon exposes one. */
    private String extractOperator(Object expression) throws Exception {
        String kind = normalizeKind(expression);
        if ("PathExpr".equals(kind)) {
            return "/";
        }
        if ("Predicate".equals(kind)) {
            return "[]";
        }

        Object tokenValue = invokeNoArgIfPresent(expression, "getOperator");
        if (tokenValue == null) {
            return null;
        }

        if (tokenValue instanceof Number number) {
            return mapOperatorCode(number.intValue(), expression.getClass().getSimpleName());
        }
        return tokenValue.toString();
    }

    /** Keeps Saxon's item type when it is available and useful for comparison. */
    private String extractValueType(Object expression) throws Exception {
        Object itemType = invokeNoArgIfPresent(expression, "getItemType");
        if (itemType != null) {
            return itemType.toString();
        }
        return null;
    }

    /** Reads literal values from Saxon literal-like expression nodes. */
    private String extractLiteralValue(Object expression) throws Exception {
        Object grounded = invokeNoArgIfPresent(expression, "getGroundedValue");
        if (grounded != null) {
            return grounded.toString();
        }
        Object value = invokeNoArgIfPresent(expression, "getValue");
        if (value != null) {
            return value.toString();
        }
        return null;
    }

    /**
     * Finds child expressions through Saxon's public expression/operand APIs.
     */
    private List<Object> childExpressions(Object expression) throws Exception {
        List<Object> children = new ArrayList<>();
        Object operands = invokeNoArgIfPresent(expression, "operands");
        if (operands instanceof Iterable<?> iterable) {
            for (Object operand : iterable) {
                Object child = invokeNoArgIfPresent(operand, "getChildExpression");
                if (child != null) {
                    children.add(child);
                }
            }
            return children;
        }

        Object child = invokeNoArgIfPresent(expression, "getChildExpression");
        if (child != null) {
            children.add(child);
            return children;
        }

        for (Method method : expression.getClass().getMethods()) {
            if (method.getParameterCount() != 0) {
                continue;
            }
            if (!method.getName().startsWith("get")) {
                continue;
            }
            if (!method.getName().endsWith("Expression") && !method.getName().endsWith("Operand")) {
                continue;
            }
            Object value = method.invoke(expression);
            addExpressionValues(children, value);
        }
        return children;
    }

    /** Adds expression objects from direct values, iterables, or arrays. */
    private void addExpressionValues(List<Object> children, Object value) throws Exception {
        if (value == null) {
            return;
        }
        if (isExpression(value)) {
            children.add(value);
            return;
        }
        if (value instanceof Iterable<?> iterable) {
            for (Object item : iterable) {
                Object child = invokeNoArgIfPresent(item, "getChildExpression");
                if (child != null) {
                    children.add(child);
                } else if (isExpression(item)) {
                    children.add(item);
                }
            }
            return;
        }
        if (value.getClass().isArray()) {
            int length = Array.getLength(value);
            for (int i = 0; i < length; i++) {
                addExpressionValues(children, Array.get(value, i));
            }
        }
    }

    /** Checks whether a reflected value is a Saxon Expression instance. */
    private boolean isExpression(Object value) {
        for (Class<?> type = value.getClass(); type != null; type = type.getSuperclass()) {
            if ("net.sf.saxon.expr.Expression".equals(type.getName())) {
                return true;
            }
        }
        return false;
    }

    /** Invokes optional no-argument Saxon methods without depending on one exact API surface. */
    private Object invokeNoArgIfPresent(Object target, String methodName) throws Exception {
        try {
            Method method = target.getClass().getMethod(methodName);
            return method.invoke(target);
        } catch (NoSuchMethodException e) {
            return null;
        } catch (InvocationTargetException e) {
            throw unwrap(e);
        }
    }

    /** Converts QName-like and display-name values into compact output names. */
    private String normalizeNamedValue(Object value) throws Exception {
        if (value == null) {
            return null;
        }
        if (value instanceof String text) {
            return normalizeNameString(text);
        }
        for (String methodName : new String[]{"getEQName", "getDisplayName", "toString"}) {
            try {
                Method method = value.getClass().getMethod(methodName);
                Object result = method.invoke(value);
                if (result != null) {
                    return normalizeNameString(result.toString());
                }
            } catch (NoSuchMethodException ignored) {
                // Try the next method.
            }
        }
        return normalizeNameString(value.toString());
    }

    /** Filters out generic Saxon labels that do not identify the expression. */
    private boolean isUsefulName(String value) {
        if (value == null || value.isBlank()) {
            return false;
        }
        return !switch (value) {
            case "functionCall", "pathExpression", "filter", "axisStep", "literal", "root", "homCheck", "sysFuncCall" -> true;
            default -> false;
        };
    }

    /** Removes parser-specific formatting and rejects names that are really expression snippets. */
    private String normalizeNameString(String value) {
        if (value == null) {
            return null;
        }

        String normalized = value.trim();
        normalized = normalized.replace("Q{urn:pmd-java}", "pmd-java:");
        normalized = normalized.replace("Q{urn:pmd}", "pmd:");

        if (normalized.equals("RootExpression")) {
            return "root";
        }

        if (normalized.contains("...") || normalized.contains("/") || normalized.contains("[") || normalized.contains("(")) {
            return null;
        }

        return normalized;
    }

    /** Supplies simple fallback names for structural root nodes. */
    private String genericNameForKind(String kind) {
        return switch (kind) {
            case "Root" -> "root";
            case "PathExpr", "Predicate" -> null;
            default -> null;
        };
    }

    /** Translates Saxon operator codes/classes into stable string labels. */
    private String mapOperatorCode(int code, String simpleName) {
        if (simpleName.toLowerCase(Locale.ROOT).contains("union")) {
            return "|";
        }
        if (simpleName.toLowerCase(Locale.ROOT).contains("and")) {
            return "and";
        }
        if (simpleName.toLowerCase(Locale.ROOT).contains("or")) {
            return "or";
        }
        if (simpleName.toLowerCase(Locale.ROOT).contains("comparison")) {
            return "comparison";
        }
        if (simpleName.toLowerCase(Locale.ROOT).contains("identity")) {
            return "is";
        }
        return String.valueOf(code);
    }

    /** Unwraps reflection exceptions so parse errors point at the real cause. */
    private Exception unwrap(InvocationTargetException e) {
        Throwable cause = e.getCause();
        if (cause instanceof Exception exception) {
            return exception;
        }
        return new Exception(cause == null ? e.getMessage() : cause.getMessage(), cause);
    }

    /** Treats missing XPath values as empty strings so errors are recorded per row. */
    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    /** Formats the deepest exception cause for parseError output. */
    private String rootCauseMessage(Throwable throwable) {
        Throwable current = throwable;
        while (current.getCause() != null) {
            current = current.getCause();
        }
        return current.getClass().getSimpleName() + ": " + current.getMessage();
    }
}
