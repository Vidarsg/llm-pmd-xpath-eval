/**
 * Positive example for PMD rule: SystemPrintln.
 */
public class SystemPrintlnPositive {

    public void methodWithPrintln() {
        System.out.println("Hello World");
    }

    public void methodWithPrint() {
        System.err.print("Error output");
    }
}
