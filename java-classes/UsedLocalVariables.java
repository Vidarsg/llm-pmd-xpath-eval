/**
 * Task 3 Negative: Local variables that ARE actually used
 */
public class UsedLocalVariables {

    public void methodWithUsedVariables() {
        String message = "I am used";
        System.out.println(message); // Variable is used

        int count = 5;
        int total = count * 2; // Variable is used
        System.out.println("Total: " + total);
    }

    public String buildString() {
        String part1 = "Hello";
        String part2 = "World";
        return part1 + " " + part2; // Both variables are used
    }
}
