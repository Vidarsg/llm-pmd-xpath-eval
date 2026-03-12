public class JpAvoidStringBuffer {
    String join(String left, String right) {
        StringBuffer buffer = new StringBuffer();
        buffer.append(left);
        buffer.append(right);
        return buffer.toString();
    }
}
