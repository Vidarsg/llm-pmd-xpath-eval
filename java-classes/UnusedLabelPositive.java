/**
 * Positive example for PMD rule: UnusedLabel.
 */
public class UnusedLabelPositive {

    public void unusedLabelExample() {
        unusedLabel: for (int i = 0; i < 3; i++) {
            System.out.println(i);
        }
    }
}
