package repo.xpath.ast;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * One input/output record for the XPath AST parser.
 *
 * <p>Each record corresponds to one JSONL line from the experiment data and
 * carries both parse status and the normalized AST.</p>
 */
public final class AstRecord {
    /** Stable identifier used to match generated and ground-truth XPath rules. */
    public Object ruleKey;

    /** Original XPath string from the input row. */
    public String xpath;

    /** True when Saxon parsed the XPath and a normalized AST was produced. */
    public boolean parseSuccess;

    /** Root-cause parse error message when parsing failed. */
    public String parseError;

    /** Normalized AST root, or null when parsing failed. */
    public AstNode ast;

    /** Experiment metadata copied through unchanged for downstream grouping. */
    public Map<String, Object> passthrough = new LinkedHashMap<>();
}
