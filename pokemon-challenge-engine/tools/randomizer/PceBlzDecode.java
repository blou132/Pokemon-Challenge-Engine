import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import cuecompressors.BLZCoder;

/**
 * In-memory bridge to the pinned ZX codec. Unlike its CLI, this never writes a
 * file. Input and output are binary pipes owned by shiny_arm9_inspect.py.
 */
class PceBlzDecode {
    public static void main(String[] args) throws Exception {
        if (args.length != 0) {
            throw new IllegalArgumentException("No file arguments are accepted");
        }
        byte[] packed = System.in.readNBytes(0x1000000);
        if (packed.length < 40 || packed.length > 0xFFFFFF) {
            throw new IllegalArgumentException("Invalid ARM9 length");
        }
        PrintStream binaryOutput = System.out;
        ByteArrayOutputStream diagnostics = new ByteArrayOutputStream();
        byte[] decoded;
        // BLZCoder's library entry point only touches the supplied byte array.
        // Its diagnostic output must not contaminate the binary response.
        try (PrintStream captured = new PrintStream(diagnostics)) {
            System.setOut(captured);
            decoded = new BLZCoder(null).BLZ_DecodePub(packed, "arm9.bin");
        } finally {
            System.setOut(binaryOutput);
        }
        if (diagnostics.size() != 0 || decoded == null) {
            System.err.println("BLZ decoding refused");
            System.exit(1);
        }
        binaryOutput.write(decoded);
    }
}
