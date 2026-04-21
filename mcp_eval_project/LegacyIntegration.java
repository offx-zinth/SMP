public class LegacyIntegration {
    public double normalizeData(double rawData) {
        return rawData / 100.0;
    }
    
    public void syncWithCore() {
        System.out.println("Syncing with Rust core...");
    }
}
