/**
 * Task 1 Negative: Methods that do NOT return int
 */
public class NonIntReturnMethods {

    // Returns String - should NOT be detected
    public String getName() {
        return "test";
    }

    // Returns void - should NOT be detected
    public void printMessage() {
        System.out.println("Hello");
    }

    // Returns boolean - should NOT be detected
    public boolean isValid() {
        return true;
    }

    // Returns double - should NOT be detected
    public double getPrice() {
        return 19.99;
    }
}
