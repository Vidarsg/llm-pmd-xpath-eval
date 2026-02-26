/**
 * Positive example for PMD rule: CollapsibleIfStatements.
 */
public class CollapsibleIfStatementsPositive {

    public void nestedIfs(int a, int b) {
        if (a > 0)
            if (b > 0)
                System.out.println("both positive");
    }
}
