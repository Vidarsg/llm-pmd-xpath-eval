/**
 * Negative example for PMD rule: AvoidThrowingRawExceptionTypes.
 */
public class AvoidThrowingRawExceptionTypesNegative {

    public static class CustomException extends Exception {
        public CustomException(String message) {
            super(message);
        }
    }

    public void throwsCustomException() throws CustomException {
        throw new CustomException("custom exception");
    }
}
