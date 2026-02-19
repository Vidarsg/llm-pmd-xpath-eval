/**
 * Task 6 Positive: Detect methods with many parameters
 */
public class MethodsWithManyParameters {

    // Method with 5 parameters - should be detected
    public void methodWithManyParams(String param1, int param2, String param3,
            boolean param4, double param5) {
        System.out.println("Called with 5 params");
    }

    // Method with 6 parameters - should be detected
    public void anotherOverloadedMethod(String a, String b, String c,
            String d, String e, String f) {
        System.out.println("Called with 6 params");
    }
}
