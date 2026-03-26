package repo.xpath.ast;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

public final class Main {
    private Main() {
    }

    public static void main(String[] args) throws Exception {
        Map<String, String> parsedArgs = parseArgs(args);
        Path input = Path.of(requireArg(parsedArgs, "--in"));
        Path output = Path.of(requireArg(parsedArgs, "--out"));

        Files.createDirectories(output.toAbsolutePath().getParent());

        ObjectMapper mapper = new ObjectMapper();
        XPathAstExtractor extractor = new XPathAstExtractor();

        try (BufferedReader reader = Files.newBufferedReader(input, StandardCharsets.UTF_8);
             BufferedWriter writer = Files.newBufferedWriter(output, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }

                Map<String, Object> row = mapper.readValue(line, new TypeReference<LinkedHashMap<String, Object>>() {});
                AstRecord record = extractor.extract(row);
                writer.write(mapper.writeValueAsString(toOutputRow(record)));
                writer.newLine();
            }
        }

        System.out.println("Wrote AST records to " + output);
    }

    private static Map<String, Object> toOutputRow(AstRecord record) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("ruleKey", record.ruleKey);
        row.put("xpath", record.xpath);
        row.put("parseSuccess", record.parseSuccess);
        row.put("parseError", record.parseError);
        row.put("ast", record.ast);
        row.putAll(record.passthrough);
        return row;
    }

    private static String requireArg(Map<String, String> parsedArgs, String key) {
        String value = parsedArgs.get(key);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Missing required argument: " + key);
        }
        return value;
    }

    private static Map<String, String> parseArgs(String[] args) {
        Map<String, String> parsed = new LinkedHashMap<>();
        for (int i = 0; i < args.length; i += 2) {
            if (i + 1 >= args.length) {
                throw new IllegalArgumentException("Arguments must be provided as --key value pairs");
            }
            parsed.put(args[i], args[i + 1]);
        }
        return parsed;
    }
}
