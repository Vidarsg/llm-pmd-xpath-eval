import java.text.DecimalFormat;
import java.text.NumberFormat;

public class JpAvoidDecimalFormatField {
    private static final NumberFormat FORMAT = new DecimalFormat("###.##");

    String format(double value) {
        return FORMAT.format(value);
    }
}
