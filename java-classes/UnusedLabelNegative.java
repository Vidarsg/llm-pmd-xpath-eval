/**
 * Negative example for PMD rule: UnusedLabel.
 */
public class UnusedLabelNegative {

    public void usedLabelExample() {
        outer: for (int i = 0; i < 3; i++) {
            if (i == 1) {
                break outer;
            }
        }
    }
}
