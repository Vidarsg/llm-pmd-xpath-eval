import java.io.IOException;

/**
 * Task 4 Negative: Catch specific exceptions (not generic)
 */
public class SpecificCatchException {

    public void catchSpecificException() {
        try {
            int x = 10 / 0;
        } catch (ArithmeticException e) {
            // Catching specific exception - should NOT be detected
            System.out.println("Arithmetic error: " + e);
        }
    }

    public void catchIOException() {
        try {
            // Some I/O operation
        } catch (IOException e) {
            // Catching specific exception - should NOT be detected
            System.out.println("IO error: " + e);
        }
    }
}
