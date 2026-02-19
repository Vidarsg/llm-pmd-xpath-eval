/**
 * Task 5 Positive: Detect non-private fields (public, protected,
 * package-private)
 */
public class NonPrivateFields {

    public String publicField = "visible to all"; // Should be detected

    protected int protectedField = 42; // Should be detected

    String packagePrivateField = "package level"; // Should be detected
}
