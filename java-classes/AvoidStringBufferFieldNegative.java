/**
 * Negative example for PMD rule: AvoidStringBufferField.
 */
public class AvoidStringBufferFieldNegative {

    private String name = "value";

    public String localBuilderOnly(String value) {
        StringBuilder local = new StringBuilder();
        local.append(value);
        return local.toString();
    }
}
