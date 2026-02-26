/**
 * Positive example for PMD rule: UseVarargs.
 */
public class UseVarargsPositive {

    public void logAll(String[] items) {
        for (String item : items) {
            System.out.println(item);
        }
    }
}
