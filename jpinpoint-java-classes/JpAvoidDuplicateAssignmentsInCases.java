public class JpAvoidDuplicateAssignmentsInCases {
    int resolveLevel(String type) {
        int level = 0;
        switch (type) {
            case "A":
                level = 42;
                break;
            case "B":
                level = 42;
                break;
            default:
                level = -1;
        }
        return level;
    }
}
