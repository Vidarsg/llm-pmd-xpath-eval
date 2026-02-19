/**
 * Task 7 Positive: Detect if-statements without braces
 */
public class IfStatementsWithoutBraces {

    public void ifWithoutBraces(boolean condition) {
        // If without braces - should be detected
        if (condition)
            System.out.println("True");
    }

    public void ifElseWithoutBraces(boolean condition) {
        // If-else without braces - should be detected
        if (condition)
            System.out.println("Yes");
        else
            System.out.println("No");
    }
}
