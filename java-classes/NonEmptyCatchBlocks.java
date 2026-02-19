/**
 * Task 2 Negative: Catch blocks with actual code (not empty)
 */
public class NonEmptyCatchBlocks {

    public void methodWithProperCatch() {
        try {
            int result = 10 / 0;
        } catch (Exception e) {
            System.out.println("Error occurred: " + e.getMessage());
        }
    }

    public void anotherProperCatch() {
        try {
            Thread.sleep(1000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
