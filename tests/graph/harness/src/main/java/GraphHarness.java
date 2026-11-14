import org.neo4j.harness.Neo4jBuilders;
import org.neo4j.configuration.connectors.BoltConnector;
import org.neo4j.configuration.helpers.SocketAddress;

/** Isolated actual Neo4j engine, for integration tests only. No authentication. */
public class GraphHarness {
    public static void main(String[] args) throws Exception {
        try (var db = Neo4jBuilders.newInProcessBuilder().withDisabledServer()
                .withConfig(BoltConnector.listen_address, new SocketAddress("127.0.0.1", 17687)).build()) {
            System.out.println("READY " + db.boltURI());
            System.out.flush();
            Thread.currentThread().join();
        }
    }
}
