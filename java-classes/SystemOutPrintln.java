/**
 * Task 8 Positive: Detect calls to System.out.println
 */
public class SystemOutPrintln {

    public void methodWithPrintln() {
        System.out.println("Hello World"); // Should be detected
    }

    public void anotherMethodWithPrintln() {
        System.out.println("Debug message"); // Should be detected
        System.out.println("Another message"); // Should be detected
    }

    public void methodWithVariant() {
        System.out.print("No newline"); // Also should be detected (starts with 'print')
    }
}
