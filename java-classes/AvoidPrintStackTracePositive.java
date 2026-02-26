/**
 * Positive example for PMD rule: AvoidPrintStackTrace.
 */
public class AvoidPrintStackTracePositive {

    public void usesPrintStackTrace() {
        try {
            int value = 10 / 0;
        } catch (ArithmeticException e) {
            e.printStackTrace();
        }
    }

    public void anotherPrintStackTrace() {
        try {
            String s = null;
            s.length();
        } catch (NullPointerException e) {
            e.printStackTrace();
        }
    }
}
