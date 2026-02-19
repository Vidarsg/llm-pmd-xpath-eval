/**
 * Task 4 Positive: Detect generic catch exceptions (Exception, Throwable)
 */
public class GenericCatchException {

    public void catchGenericException() {
        try {
            int x = 10 / 0;
        } catch (Exception e) {
            // Catching generic Exception - should be detected
            System.out.println("Caught: " + e);
        }
    }

    public void catchThrowable() {
        try {
            Thread.sleep(1000);
        } catch (Throwable t) {
            // Catching Throwable - should be detected
            System.out.println("Error: " + t);
        }
    }
}
