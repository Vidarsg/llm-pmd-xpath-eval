import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Negative example for PMD rule: AvoidPrintStackTrace.
 */
public class AvoidPrintStackTraceNegative {
    private static final Logger LOGGER = Logger.getLogger(AvoidPrintStackTraceNegative.class.getName());

    public void logsInsteadOfPrintStackTrace() {
        try {
            int value = 10 / 0;
        } catch (ArithmeticException e) {
            LOGGER.log(Level.WARNING, "Arithmetic error", e);
        }
    }
}
