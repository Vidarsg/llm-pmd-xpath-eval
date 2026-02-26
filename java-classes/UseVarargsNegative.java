/**
 * Negative example for PMD rule: UseVarargs.
 */
public class UseVarargsNegative {

    public void logAll(String... items) {
        for (String item : items) {
            System.out.println(item);
        }
    }
}
