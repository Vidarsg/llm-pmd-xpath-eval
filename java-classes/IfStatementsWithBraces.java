/**
 * Task 7 Negative: If-statements with proper braces
 */
public class IfStatementsWithBraces {

    public void ifWithBraces(boolean condition) {
        // If with braces - should NOT be detected
        if (condition) {
            System.out.println("True");
        }
    }

    public void ifElseWithBraces(boolean condition) {
        // If-else with braces - should NOT be detected
        if (condition) {
            System.out.println("Yes");
        } else {
            System.out.println("No");
        }
    }

    public void complexConditionWithBraces(int x, int y) {
        if (x > y) {
            System.out.println("X is greater");
        } else if (x < y) {
            System.out.println("Y is greater");
        } else {
            System.out.println("Equal");
        }
    }
}
