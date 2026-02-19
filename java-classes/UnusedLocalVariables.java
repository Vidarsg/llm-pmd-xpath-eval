/**
 * Task 3 Positive: Detect unused local variables
 */
public class UnusedLocalVariables {

    public void methodWithUnusedVariable() {
        String unused = "I am not used"; // Should be detected
        int x = 5; // Should be detected
        System.out.println("Hello");
    }

    public int anotherUnusedVariable() {
        int result = 100; // Should be detected
        String message = "ignored"; // Should be detected
        return 42;
    }
}
