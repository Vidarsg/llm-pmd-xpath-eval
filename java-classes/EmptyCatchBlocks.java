/**
 * Task 2 Positive: Detect empty catch blocks
 */
public class EmptyCatchBlocks {

    public void methodWithEmptyCatch() {
        try {
            int result = 10 / 0;
        } catch (Exception e) {
            // Empty catch block - should be detected
        }
    }

    public void anotherEmptyCatch() {
        try {
            Thread.sleep(1000);
        } catch (InterruptedException e) {
            // Nothing here - should be detected
        }
    }
}
