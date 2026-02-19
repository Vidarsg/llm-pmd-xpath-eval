/**
 * Task 1 Positive: Detect methods whose return type is int
 */
public class IntReturnMethods {

    // This method returns int - should be detected
    public int getValue() {
        return 42;
    }

    // This method also returns int - should be detected
    public int calculateSum(int a, int b) {
        return a + b;
    }

    // This method returns int - should be detected
    int getCount() {
        return 0;
    }
}
