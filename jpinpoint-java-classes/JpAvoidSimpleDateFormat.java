import java.text.SimpleDateFormat;
import java.util.Date;

public class JpAvoidSimpleDateFormat {
    String toKey(Date date) {
        SimpleDateFormat formatter = new SimpleDateFormat("yyyy-MM-dd");
        return formatter.format(date);
    }
}
