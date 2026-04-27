package repo.xpath.ast;

import java.util.ArrayList;
import java.util.List;

/**
 * Parser-independent AST node written to JSON for structural comparison.
 *
 * <p>The fields are public intentionally: Jackson serializes this simple data
 * object directly, and the rest of the tool treats it as an output DTO.</p>
 */
public final class AstNode {
    /** Coarse syntax category such as PathExpr, Predicate, FunctionCall, or Literal. */
    public String kind;

    /** Optional display name, for example a function name, node-test name, or QName. */
    public String name;

    /** Optional operator marker such as "/", "[]", "|", "and", or "or". */
    public String operator;

    /** Optional Saxon item type for literal or expression nodes when available. */
    public String valueType;

    /** Optional literal value or Saxon value string when retaining it is useful. */
    public String value;

    /** Child nodes in the same order Saxon exposes the expression operands. */
    public final List<AstNode> children = new ArrayList<>();

    public AstNode(String kind) {
        this.kind = kind;
    }
}
