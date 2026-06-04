# XPath AST Schema

This schema defines the normalized AST format used for structural similarity
comparisons between generated PMD XPath rules and reference rules.

The goal is not to preserve every parser-specific detail. The goal is to retain
stable structural information that can be compared across equivalent parses.

## Top-Level Record

Each input record should be one JSON object per line:

```json
{
  "ruleKey": "UseVarargs",
  "xpath": "//FormalParameters/FormalParameter[@Varargs = false()]",
  "parseSuccess": true,
  "parseError": null,
  "ast": {
    "kind": "PathExpr",
    "name": null,
    "operator": "/",
    "valueType": null,
    "value": null,
    "children": [
      {
        "kind": "Step",
        "name": "FormalParameters",
        "operator": null,
        "valueType": null,
        "value": null,
        "children": []
      }
    ]
  }
}
```

## Required Top-Level Fields

- `ruleKey`
  - Stable identifier used to pair an LLM rule with the corresponding reference rule.
- `xpath`
  - Original XPath string.
- `parseSuccess`
  - `true` when the parser produced an AST.
- `ast`
  - Normalized AST root node when parsing succeeded.

## Optional Top-Level Fields

- `parseError`
  - String error message if parsing failed.
- `model`
- `promptStyle`
- `target`
- `temperature`

These optional fields are preserved if present and can be carried into the
comparison output.

## AST Node Schema

Each AST node should have this shape:

```json
{
  "kind": "Predicate",
  "name": null,
  "operator": null,
  "valueType": null,
  "value": null,
  "children": []
}
```

### Required Node Field

- `kind`
  - Coarse syntactic category.

### Optional Node Fields

- `name`
  - Function name, step name, axis name, attribute name, QName, etc.
- `operator`
  - Binary or unary operator such as `/`, `//`, `|`, `and`, `or`, `=`.
- `valueType`
  - Literal type such as `string`, `int`, `boolean`.
- `value`
  - Normalized literal value when retaining it is useful.
- `children`
  - Ordered list of child nodes. Use `[]` when there are no children.

## Recommended `kind` Values

Keep the vocabulary small and parser-independent. Recommended values:

- `Root`
- `PathExpr`
- `Step`
- `Predicate`
- `FunctionCall`
- `Attribute`
- `AxisStep`
- `BinaryOp`
- `UnaryOp`
- `Literal`
- `VariableRef`
- `NodeTest`
- `SequenceExpr`

## Feature Set Used For Comparison

The structural comparison script derives these feature families:

- Node label multiset
  - `kind|name|operator`
- Edge label multiset
  - `parent_label -> child_label`
- Scalar features
  - `node_count`
  - `max_depth`
  - `predicate_count`
  - `union_count`
  - `function_count`
  - `axis_step_count`
  - `literal_count`

## Structural Similarity Metrics

The comparison script computes:

- `nodeLabelJaccard`
  - Weighted Jaccard similarity over node label multisets
- `edgeLabelJaccard`
  - Weighted Jaccard similarity over edge label multisets
- `scalarFeatureSimilarity`
  - Mean similarity over scalar feature counts
- `overallStructuralSimilarity`
  - Average of the three metrics above

This metric is intended to measure structural formulation similarity, not
behavioral or semantic equivalence.
