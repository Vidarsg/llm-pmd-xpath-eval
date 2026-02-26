/**
 * Positive example for PMD rule: AvoidStringBufferField.
 */
public class AvoidStringBufferFieldPositive {

    private StringBuffer buffer = new StringBuffer();
    private StringBuilder builder = new StringBuilder();

    public void appendData(String value) {
        buffer.append(value);
        builder.append(value);
    }
}
