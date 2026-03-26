package repo.xpath.ast;

import java.util.LinkedHashMap;
import java.util.Map;

public final class AstRecord {
    public Object ruleKey;
    public String xpath;
    public boolean parseSuccess;
    public String parseError;
    public AstNode ast;
    public Map<String, Object> passthrough = new LinkedHashMap<>();
}
