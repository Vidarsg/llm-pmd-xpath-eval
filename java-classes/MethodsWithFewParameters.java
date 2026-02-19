/**
 * Task 6 Negative: Methods with few parameters (not too many)
 */
public class MethodsWithFewParameters {

    // Simple method with 1 parameter - should NOT be detected
    public void simpleMethod(String param) {
        System.out.println(param);
    }

    // Method with 2 parameters - should NOT be detected
    public int add(int a, int b) {
        return a + b;
    }

    // Method with 3 parameters - should NOT be detected
    public void printDetails(String name, int age, boolean active) {
        System.out.println(name + " " + age + " " + active);
    }
}
