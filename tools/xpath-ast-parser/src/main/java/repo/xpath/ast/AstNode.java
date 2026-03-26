package repo.xpath.ast;

import java.util.ArrayList;
import java.util.List;

public final class AstNode {
    public String kind;
    public String name;
    public String operator;
    public String valueType;
    public String value;
    public final List<AstNode> children = new ArrayList<>();

    public AstNode(String kind) {
        this.kind = kind;
    }
}
