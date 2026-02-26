/**
 * Positive example for PMD rule: AvoidThrowingRawExceptionTypes.
 */
public class AvoidThrowingRawExceptionTypesPositive {

    public void throwsRuntimeException() {
        throw new RuntimeException("raw exception");
    }

    public void throwsException() throws Exception {
        throw new Exception("raw exception");
    }
}
