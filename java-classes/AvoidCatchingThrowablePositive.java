/**
 * Positive example for PMD rule: AvoidCatchingThrowable.
 */
public class AvoidCatchingThrowablePositive {

    public void catchThrowable() {
        try {
            Thread.sleep(1000);
        } catch (Throwable t) {
            System.err.println(t.getMessage());
        }
    }
}
