import java.util.logging.Logger;

/**
 * Negative example for PMD rule: SystemPrintln.
 */
public class SystemPrintlnNegative {
    private static final Logger LOGGER = Logger.getLogger(SystemPrintlnNegative.class.getName());

    public void methodWithLogger() {
        LOGGER.info("Info message");
    }
}
