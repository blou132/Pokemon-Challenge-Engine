import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import cuecompressors.BLZCoder;

/** In-memory overlay encoder using the pinned ZX codec. No file arguments. */
class PceBlzEncode {
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("No file arguments");
        byte[] input = System.in.readNBytes(0x1000000);
        if (input.length < 40 || input.length > 0xFFFFFF)
            throw new IllegalArgumentException("Invalid overlay length");
        PrintStream binaryOutput = System.out;
        ByteArrayOutputStream diagnostics = new ByteArrayOutputStream();
        byte[] encoded;
        try (PrintStream captured = new PrintStream(diagnostics)) {
            System.setOut(captured);
            encoded = new BLZCoder(null).BLZ_EncodePub(input, false, false, "overlay");
        } finally {
            System.setOut(binaryOutput);
        }
        if (encoded == null || !diagnostics.toString("UTF-8").matches(
                "- encoding 'overlay' \\(memory\\) - done, time=[0-9]+ms\\s*")) {
            System.err.println("BLZ encoding refused");
            System.exit(1);
        }
        binaryOutput.write(encoded);
    }
}
