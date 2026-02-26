/**
 * Negative example for PMD rule: AvoidCatchingThrowable.
 */
public class AvoidCatchingThrowableNegative {

    public void catchSpecificException() {
        try {
            int x = 10 / 0;
        } catch (ArithmeticException e) {
            System.err.println(e.getMessage());
        }
    }
}
