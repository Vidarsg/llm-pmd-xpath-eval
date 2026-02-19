import java.util.logging.Logger;

/**
 * Task 8 Negative: No calls to System.out.println (uses logger instead)
 */
public class NoSystemOutPrintln {

    private static final Logger logger = Logger.getLogger(NoSystemOutPrintln.class.getName());

    public void methodWithoutPrintln() {
        logger.info("Info message"); // Uses logger instead
    }

    public void anotherMethodWithLogger() {
        logger.warning("Warning message");
        logger.severe("Error message");
    }

    public void methodWithOtherOutput() {
        // No System.out calls
        int result = 5 + 3;
    }
}
