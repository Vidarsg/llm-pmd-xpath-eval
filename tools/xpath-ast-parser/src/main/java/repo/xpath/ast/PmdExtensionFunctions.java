package repo.xpath.ast;

import net.sf.saxon.expr.XPathContext;
import net.sf.saxon.lib.ExtensionFunctionCall;
import net.sf.saxon.lib.ExtensionFunctionDefinition;
import net.sf.saxon.om.Sequence;
import net.sf.saxon.om.StructuredQName;
import net.sf.saxon.value.BooleanValue;
import net.sf.saxon.value.SequenceType;
import net.sf.saxon.value.StringValue;

public final class PmdExtensionFunctions {
    private PmdExtensionFunctions() {
    }

    public static void registerAll(net.sf.saxon.Configuration configuration) {
        configuration.registerExtensionFunction(booleanFunction("urn:pmd-java", "typeIs", 1, 1));
        configuration.registerExtensionFunction(booleanFunction("urn:pmd-java", "typeIsExactly", 1, 1));
        configuration.registerExtensionFunction(booleanFunction("urn:pmd-java", "matchesSig", 1, 2));
        configuration.registerExtensionFunction(booleanFunction("urn:pmd-java", "hasAnnotation", 1, 1));
        configuration.registerExtensionFunction(booleanFunction("urn:pmd-java", "nodeIs", 1, 1));
        configuration.registerExtensionFunction(stringFunction("urn:pmd-java", "modifiers", 0, 0));
    }

    private static ExtensionFunctionDefinition booleanFunction(String uri, String localName, int minArity, int maxArity) {
        return new ExtensionFunctionDefinition() {
            @Override
            public StructuredQName getFunctionQName() {
                return new StructuredQName("pmd-java", uri, localName);
            }

            @Override
            public int getMinimumNumberOfArguments() {
                return minArity;
            }

            @Override
            public int getMaximumNumberOfArguments() {
                return maxArity;
            }

            @Override
            public SequenceType[] getArgumentTypes() {
                SequenceType[] types = new SequenceType[maxArity];
                for (int i = 0; i < maxArity; i++) {
                    types[i] = SequenceType.ANY_SEQUENCE;
                }
                return types;
            }

            @Override
            public SequenceType getResultType(SequenceType[] suppliedArgumentTypes) {
                return SequenceType.SINGLE_BOOLEAN;
            }

            @Override
            public ExtensionFunctionCall makeCallExpression() {
                return new ExtensionFunctionCall() {
                    @Override
                    public Sequence call(XPathContext context, Sequence[] arguments) {
                        return BooleanValue.FALSE;
                    }
                };
            }
        };
    }

    private static ExtensionFunctionDefinition stringFunction(String uri, String localName, int minArity, int maxArity) {
        return new ExtensionFunctionDefinition() {
            @Override
            public StructuredQName getFunctionQName() {
                return new StructuredQName("pmd-java", uri, localName);
            }

            @Override
            public int getMinimumNumberOfArguments() {
                return minArity;
            }

            @Override
            public int getMaximumNumberOfArguments() {
                return maxArity;
            }

            @Override
            public SequenceType[] getArgumentTypes() {
                return new SequenceType[0];
            }

            @Override
            public SequenceType getResultType(SequenceType[] suppliedArgumentTypes) {
                return SequenceType.OPTIONAL_STRING;
            }

            @Override
            public ExtensionFunctionCall makeCallExpression() {
                return new ExtensionFunctionCall() {
                    @Override
                    public Sequence call(XPathContext context, Sequence[] arguments) {
                        return StringValue.EMPTY_STRING;
                    }
                };
            }
        };
    }
}
