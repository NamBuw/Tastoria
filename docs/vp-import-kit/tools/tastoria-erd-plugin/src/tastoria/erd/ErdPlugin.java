package tastoria.erd;

import com.vp.plugin.*;
import com.vp.plugin.diagram.*;
import com.vp.plugin.model.*;
import com.vp.plugin.model.factory.IModelElementFactory;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** CLI: Plugin.sh -project X.vpp -pluginid tastoria.erd -pluginargs -spec erd-spec.tsv */
public class ErdPlugin implements VPPlugin, VPPluginCommandLineSupport {
    /** PostgreSQL spellings that VP's PostgreSQL type list knows under another name. */
    static final Map<String, String> PG_ALIAS = new HashMap<>();
    static {
        PG_ALIAS.put("timestamptz", "timestamp with time zone");
        PG_ALIAS.put("boolean", "bool");
        PG_ALIAS.put("bigserial", "int8");
    }
    public void loaded(VPPluginInfo info) {}
    public void unloaded() {}

    public void invoke(String[] args) {
        String spec = null;
        for (int i = 0; i < args.length - 1; i++) if ("-spec".equals(args[i])) spec = args[i + 1];
        for (int i = 0; i < args.length; i++) if ("-probe".equals(args[i])) { probe(); return; }
        for (int i = 0; i < args.length; i++) if ("-relayout-seq".equals(args[i])) { relayoutSequences(); return; }
        if (spec == null) { System.out.println("Usage: -spec <tsv>"); return; }
        try { build(Paths.get(spec)); }
        catch (Throwable t) { t.printStackTrace(System.out); System.out.println("ERD-BUILD-FAILED"); }
    }

    /** PlantUML-VP drops every lifeline at x=0; spread them left to right in creation order. */
    private void relayoutSequences() {
        ProjectManager pm = ApplicationManager.instance().getProjectManager();
        int n = 0;
        for (IDiagramUIModel d : pm.getProject().toDiagramArray()) {
            if (!(d instanceof IInteractionDiagramUIModel)) continue;
            int x = 20;
            for (IDiagramElement e : d.toDiagramElementArray()) {
                if (e instanceof com.vp.plugin.diagram.shape.IInteractionLifeLineUIModel
                        || e instanceof com.vp.plugin.diagram.shape.IInteractionActorUIModel) {
                    IShapeUIModel sh = (IShapeUIModel) e;
                    sh.setX(x);
                    x += Math.max(sh.getWidth(), 120) + 220;
                }
            }
            n++;
        }
        pm.saveProject();
        System.out.println("RELAYOUT-SEQ-OK " + n + " sequence diagrams");
    }

    private void usePostgres() {
        // Make PostgreSQL the project's default database so column types use its type list (uuid, text, timestamptz...)
        ProjectManager pm = ApplicationManager.instance().getProjectManager();
        DatabaseSetting ds = pm.loadDatabaseSetting(pm.getProject(), DatabaseType.PostgreSQL, DatabaseLanguage.Java);
        if (ds == null) ds = new DatabaseSetting();
        ds.setSupported(true);
        ds.setDefault(true);
        ds.setDialect(DatabaseSetting.DIALECT_POSTGRESQL);
        pm.saveDatabaseSetting(pm.getProject(), DatabaseType.PostgreSQL, DatabaseLanguage.Java, ds);
    }

    private void probe() {
        usePostgres();
        IDBTable t = IModelElementFactory.instance().createDBTable();
        String[] names = {"timestamptz","timestamp with time zone","timestamp(6) with time zone","timestamp","boolean","bool","jsonb","json","bigserial","serial8","bigint","int8","numeric","real","float4","date","integer","smallint","text","uuid","timestamptz","timestamp","timestamp with time zone","boolean","bool","bytea","blob","bigserial","serial","jsonb","json","varchar","char","clob","longvarchar","bit","binary","varbinary","double","float","decimal","tinyint","time","uniqueidentifier","guid","long varchar","character varying","integer"};
        for (String n : names) {
            IDBColumn c = t.createDBColumn();
            boolean ok = c.setType(n, 0, 0);
            System.out.println("PROBE setType(" + n + ")=" + ok + " typeName=" + c.getTypeName() + " type=" + c.getType());
        }
        IDBColumn c = t.createDBColumn();
        c.setTypeName("uuid");
        System.out.println("PROBE setTypeName(uuid) -> typeName=" + c.getTypeName() + " type=" + c.getType() + " user=" + c.getUserType());
        IDBColumn c2 = t.createDBColumn();
        c2.setUserType("uuid");
        System.out.println("PROBE setUserType(uuid) -> typeName=" + c2.getTypeName() + " type=" + c2.getType() + " user=" + c2.getUserType());
    }

    private void build(Path spec) throws Exception {
        usePostgres();
        IModelElementFactory f = IModelElementFactory.instance();
        DiagramManager dm = ApplicationManager.instance().getDiagramManager();
        Map<String, IDBTable> tables = new LinkedHashMap<>();
        Map<String, IDBColumn> cols = new HashMap<>();
        List<String[]> fks = new ArrayList<>(), groups = new ArrayList<>();
        int typeOk = 0, typeUser = 0;
        for (String line : Files.readAllLines(spec, StandardCharsets.UTF_8)) {
            if (line.isEmpty()) continue;
            String[] p = line.split("\t", -1);
            switch (p[0]) {
                case "T": {
                    IDBTable t = f.createDBTable();
                    t.setName(p[1]);
                    t.setDocumentation(p[3] + (p[2].isEmpty() ? "" : "\n[module " + p[2] + "]"));
                    tables.put(p[1], t);
                    break;
                }
                case "C": {
                    IDBTable t = tables.get(p[1]);
                    IDBColumn c = t.createDBColumn();
                    c.setName(p[2]);
                    int len = Integer.parseInt(p[4]), scale = Integer.parseInt(p[5]);
                    // VP's generic type list lacks PostgreSQL names (text, uuid, timestamptz, ...): keep the exact name as type name
                    String vpType = PG_ALIAS.getOrDefault(p[3], p[3]);
                    if (c.setType(vpType, len, scale)) typeOk++; else {
                        // not in VP's PostgreSQL list (jsonb): record it as a PostgreSQL user type
                        IDBColumnUserType ut = f.createDBColumnUserType();
                        ut.setType(p[3]);
                        ut.setDbType(DatabaseType.PostgreSQL.ordinal());
                        c.addUserType(ut);
                        c.setUserType(p[3]); typeUser++; System.out.println("user type " + p[1] + "." + p[2] + " " + p[3]); }
                    c.setNullable(!"1".equals(p[6]));
                    if (!p[7].isEmpty()) c.setDefaultValue(p[7]);
                    c.setPrimaryKey("1".equals(p[8]));
                    if ("1".equals(p[9])) c.setUnique(true);
                    String doc = p[10];
                    if ("bigserial".equals(p[3])) doc = "[bigserial: int8 + sequence] " + doc;
                    if ("jsonb".equals(p[3])) doc = "[PostgreSQL type: jsonb - VP has no jsonb in its type list] " + doc;
                    if (!doc.isEmpty()) c.setDocumentation(doc);
                    cols.put(p[1] + "." + p[2], c);
                    break;
                }
                case "F": fks.add(p); break;
                case "G": groups.add(p); break;
            }
        }
        Map<String, IDBForeignKey> fkModels = new LinkedHashMap<>();
        Map<String, String[]> fkEnds = new HashMap<>();
        for (String[] p : fks) {
            // F name child cols parent refcols ondelete
            IDBTable child = tables.get(p[2]), parent = tables.get(p[4]);
            IDBForeignKey fk = f.createDBForeignKey();
            fk.setName(p[1]);
            fk.setFrom(parent);
            fk.setTo(child);
            String od = p[6];
            if ("CASCADE".equals(od)) fk.setOnDelete(IDBForeignKey.ON_DELETE_CASCADE);
            else if ("SET NULL".equals(od)) fk.setOnDelete(IDBForeignKey.ON_DELETE_SET_NULL);
            else if ("SET DEFAULT".equals(od)) fk.setOnDelete(IDBForeignKey.ON_DELETE_SET_DEFAULT);
            else if ("RESTRICT".equals(od)) fk.setOnDelete(IDBForeignKey.ON_DELETE_RESTRICT);
            else if ("NO ACTION".equals(od)) fk.setOnDelete(IDBForeignKey.ON_DELETE_NO_ACTION);
            String[] cc = p[3].split(","), rc = p[5].split(",");
            for (int i = 0; i < cc.length; i++) {
                IDBColumn ccol = cols.get(p[2] + "." + cc[i].trim()), rcol = cols.get(p[4] + "." + rc[i].trim());
                if (ccol == null || rcol == null) { System.out.println("WARN missing column for " + p[1]); continue; }
                IDBForeignKeyConstraint k = f.createDBForeignKeyConstraint();
                k.setRefColumn(rcol);
                k.setForeignKey(fk);
                ccol.addForeignKeyConstraint(k);
            }
            fkModels.put(p[1], fk);
            fkEnds.put(p[1], new String[]{p[4], p[2]});
        }
        int conns = 0;
        Set<IDBColumn> specCols = new HashSet<>(cols.values());
        for (String[] g : groups) {
            // G id title tables
            IERDiagramUIModel d = (IERDiagramUIModel) dm.createDiagram(IDiagramTypeConstants.DIAGRAM_TYPE_ER_DIAGRAM);
            d.setName(g[1]);
            d.setDocumentation(g[2]);
            LinkedHashSet<String> onDiagram = new LinkedHashSet<>(Arrays.asList(g[3].split(",")));
            Set<String> home = new HashSet<>(onDiagram);
            // add referenced tables from other groups so every FK of the group is visible
            for (Map.Entry<String, String[]> e : fkEnds.entrySet()) {
                String parent = e.getValue()[0], child = e.getValue()[1];
                if (home.contains(child)) onDiagram.add(parent);
            }
            Map<String, IDiagramElement> shapes = new HashMap<>();
            for (String tn : onDiagram) {
                IShapeUIModel s = (IShapeUIModel) dm.createDiagramElement(d, tables.get(tn));
                s.fitSize();
                shapes.put(tn, s);
            }
            for (Map.Entry<String, String[]> e : fkEnds.entrySet()) {
                String parent = e.getValue()[0], child = e.getValue()[1];
                if (!home.contains(child) || !shapes.containsKey(parent)) continue;
                try {
                    dm.createConnector(d, fkModels.get(e.getKey()), shapes.get(parent), shapes.get(child), null);
                    conns++;
                } catch (IllegalArgumentException ex) { System.out.println("WARN connector " + e.getKey() + ": " + ex.getMessage()); }
            }
            System.out.println("diagram " + g[1] + ": " + onDiagram.size() + " tables (" + home.size() + " home)");
        }
        // createConnector() makes VP add its own FK columns (e.g. "usersid"); the spec already has the real
        // FK columns linked through IDBForeignKeyConstraint, so drop the generated ones.
        int removed = 0;
        for (IDBTable t : tables.values()) {
            for (IDBColumn c : t.toDBColumnArray()) {
                if (!specCols.contains(c)) { t.removeDBColumn(c); c.delete(); removed++; }
            }
        }
        System.out.println("removed auto FK columns: " + removed);
        for (IDiagramUIModel d : ApplicationManager.instance().getProjectManager().getProject().toDiagramArray()) {
            for (IDiagramElement e : d.toDiagramElementArray()) if (e instanceof IShapeUIModel) ((IShapeUIModel) e).fitSize();
            dm.layout(d, DiagramManager.LAYOUT_ORTHOGONAL);
        }
        System.out.println("tables=" + tables.size() + " columns=" + cols.size() + " fks=" + fkModels.size()
                + " connectors=" + conns + " typeOk=" + typeOk + " typeUser=" + typeUser);
        ApplicationManager.instance().getProjectManager().saveProject();
        System.out.println("ERD-BUILD-OK");
    }
}
