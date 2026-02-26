/**
 * Negative example for PMD rule: CollapsibleIfStatements.
 */
public class CollapsibleIfStatementsNegative {

    public void nonCollapsibleIfs(int a, int b) {
        if (a > 0) {
            if (b > 0) {
                System.out.println("both positive");
            } else {
                System.out.println("a only");
            }
        }
    }
}
