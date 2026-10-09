"""C# symbols, namespace usings, injection, tests and dotnet manifests."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from cbi.build import SHOWN
from cbi.cli import main
from cbi.files import PARSER_VERSION
from cbi.parse import csharp
from cbi.store import SCHEMA_VERSION

GOLDEN = Path(__file__).parent / "golden" / "csharp.txt"
WS = "local:repo"

SNIPPET = """\
global using Global.Ns;
using static System.Math;
using Alias = App.Widget;
using Other.Ns;

namespace App.Services;

/// <summary>
/// A widget.
/// </summary>
public partial class Widget : Store
{
    /// <summary>The name.</summary>
    public string Name { get; set; }

    public Widget(IClock clock)
    {
        this.clock = clock;
    }

    public void Run()
    {
        Helper();
        this.Go();
        base.Save();
        Clock.Tick();
        clock.Now();
        var key = configuration["CONN"] ?? "c";
        var token = Environment.GetEnvironmentVariable(variable: "API_KEY") ?? "none";
    }

    public void Helper() {}

    public void Go() {}
}

public record Point(int X, int Y);

public record Person
{
    public string Name { get; set; }
}

public record struct Coord(int X);

file class Hidden {}

public interface IClock
{
    string Now();
}

public enum Kind
{
    One,
}

public class Box<T> : IList<T>
{
    public void M<U>(T item) {}
}

public class Primary(IClock widget)
{
    public void Go()
    {
        widget.Do();
    }
}

#if DEBUG
public class WhenDebug {}
#else
public class WhenElse {}
#endif
"""

TESTS = """\
public class Cases
{
    [Fact]
    public void A() {}

    [Theory]
    public void B() {}

    [Test]
    public void C() {}

    [TestMethod]
    public void D() {}

    [Xunit.FactAttribute]
    public void E() {}
}
"""

FILES = {
    "App/IClock.cs": """\
namespace App;

public interface IClock
{
    string Now();
}
""",
    "App/SystemClock.cs": """\
namespace App;

public class SystemClock : IClock
{
    public string Now() => "t";
}
""",
    "App/Calls.cs": """\
namespace App;

public class Store
{
    public void Save() {}
}

public class Child : Store
{
    public void Run()
    {
        base.Save();
        Clock.Tick();
    }
}

public class Clock
{
    public static void Tick() {}
}
""",
    "App/Widget.cs": """\
namespace App.Services;

/// <summary>A widget.</summary>
public partial class Widget
{
    public string Name { get; set; }

    private readonly IClock clock;

    public Widget(IClock clock)
    {
        this.clock = clock;
    }

    public string Run()
    {
        Helper();
        this.Go();
        Extra();
        Pick(1);
        var key = configuration["CONN"] ?? "c";
        var token = Environment.GetEnvironmentVariable("API_KEY") ?? "none";
        return clock.Now() + key + token;
    }

    public void Helper() {}

    public void Go() {}

    public int Pick(int a) => a;

    public int Pick(int a, int b) => b;
}
""",
    "App/Widget.More.cs": """\
namespace App.Services;

public partial class Widget
{
    public void Extra() {}
}
""",
    "App/ViaGlobal.cs": """\
namespace App.Services;

public class ViaGlobal
{
    public void Go()
    {
        Thing.Ping();
        Widget.Extra();
    }
}
""",
    "App/UsesAlias.cs": """\
using Alias = App.Services.Widget;

namespace Elsewhere;

public class UsesAlias
{
    public void Go()
    {
        Alias.Extra();
    }
}
""",
    "App/Box.cs": """\
namespace App;

public interface ILogger
{
    void Write();
}

public class ConsoleLogger : ILogger
{
    public void Write() {}
}

public record Box(ILogger logger)
{
    public void Save()
    {
        logger.Write();
    }
}
""",
    "App/Holder.cs": """\
namespace App;

public struct Counter
{
    public int Value { get; set; }

    public void Inc() {}
}

public class Holder
{
    private readonly Counter counter;

    public Holder(Counter counter)
    {
        this.counter = counter;
    }

    public void Bump()
    {
        counter.Inc();
    }
}
""",
    "App/Sneaky.cs": """\
namespace App;

public class Sneaky
{
    [Fact]
    public void Hidden() {}
}
""",
    "App/Program.cs": """\
namespace App;

public class Program
{
    public static void Main(string[] args) {}
}
""",
    "App/App.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <ItemGroup>
    <Using Include="App" />
    <Using Include="Other" />
    <Using Static="True" Include="System.Math" />
    <ProjectReference Include="../Lib/Lib.csproj" />
  </ItemGroup>
</Project>
""",
    "Other/Thing.cs": """\
namespace Other;

public static class Thing
{
    public static void Ping() {}
}
""",
    "Other/Other.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
</Project>
""",
    "Lib/Lib.cs": """\
namespace Lib;

public class LibThing {}
""",
    "Lib/Lib.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
</Project>
""",
    "Elsewhere/Mentions.cs": """\
namespace Elsewhere;

public class Mentions
{
    private readonly App.IClock clock;
}
""",
    "App.Tests/WidgetTests.cs": """\
namespace App.Tests;

public class WidgetTests
{
    [Fact]
    public void Run_writes()
    {
        IClock clock = new SystemClock();
        new Widget(clock).Run();
    }

    [Theory]
    public void Picks(int n) {}

    [Test]
    public void NUnitOne() {}

    [TestMethod]
    public void MsOne() {}
}
""",
    "App.Tests/Helper.cs": """\
namespace App.Tests;

public class Helper {}
""",
    "App.Tests/App.Tests.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <ItemGroup>
    <Using Include="App" />
    <Using Include="App.Services" />
    <ProjectReference Include="../App/App.csproj" />
  </ItemGroup>
</Project>
""",
    "Lonely.Tests/LonelyTests.cs": """\
using Missing.Ns;

namespace Lonely.Tests;

public class LonelyTests
{
    [Fact]
    public void Nothing() {}
}
""",
    "Lonely.Tests/Lonely.Tests.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
</Project>
""",
    "Cli/Program.cs": """\
namespace Cli;

public class Program
{
    public static void Main() {}
}
""",
    "Cli/Cli.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
  </PropertyGroup>
</Project>
""",
    "Tools/Program.cs": """\
namespace Tools;

public class Program
{
    public static void Main() {}
}
""",
    "Tools/Tools.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
  </PropertyGroup>
</Project>
""",
    "Gap/Gap.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
</Project>
""",
    "Both/Program.cs": """\
namespace Both;

public class Program
{
    public static void Main() {}
}
""",
    "Both/Both.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
  </PropertyGroup>
</Project>
""",
    "App.sln": """\
Microsoft Visual Studio Solution File, Format Version 12.00
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "App", "App/App.csproj", "{11111111-1111-1111-1111-111111111111}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Lib", "Lib/Lib.csproj", "{22222222-2222-2222-2222-222222222222}"
EndProject
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "Solution Items", "Solution Items", "{33333333-3333-3333-3333-333333333333}"
EndProject
""",
    "Bad.cs": "class {\n",
}


def _parse(source, is_test=False):
    defs, facts, err = csharp.parse(source.encode(), "csharp", is_test)
    return defs, facts, err


def _qual(defs, index):
    return None if index is None else defs[index]["qualname"]


def _calls(defs, facts):
    return [
        (_qual(defs, src), shape, name, member)
        for src, _cls, shape, name, member, *_extra in facts["calls"]
    ]


def test_parser_versions_stay_put():
    assert PARSER_VERSION == 19
    assert SCHEMA_VERSION == 6
    assert "property" not in SHOWN
    assert "constructor" not in SHOWN


def test_csharp_symbols_docs_and_facts():
    defs, facts, err = _parse(SNIPPET)
    assert not err
    by = {d["qualname"]: d for d in defs}
    widget = by["App.Services.Widget"]
    assert widget["display_kind"] == "class"
    assert widget["doc"] == "A widget."
    assert widget["signature"].startswith("public partial class Widget")
    assert by["App.Services.Widget.Name"]["display_kind"] == "property"
    assert by["App.Services.Widget.Name"]["doc"] == "The name."
    assert by["App.Services.Widget.Widget"]["display_kind"] == "constructor"
    assert by["App.Services.Widget.Run"]["display_kind"] == "method"
    assert by["App.Services.Point"]["display_kind"] == "record"
    assert by["App.Services.Point.X"]["display_kind"] == "property"
    assert by["App.Services.Point.Y"]["display_kind"] == "property"
    assert by["App.Services.Person.Name"]["display_kind"] == "property"
    assert by["App.Services.Coord"]["display_kind"] == "record"
    assert by["App.Services.Coord.X"]["display_kind"] == "property"
    assert by["App.Services.Hidden"]["display_kind"] == "class"
    assert by["App.Services.IClock"]["display_kind"] == "interface"
    assert by["App.Services.IClock.Now"]["signature"] == "string Now();"
    assert by["App.Services.Kind"]["display_kind"] == "enum"
    assert "App.Services.Kind.One" not in by
    assert by["App.Services.Box.M"]["display_kind"] == "method"
    assert "App.Services.Primary.widget" not in by
    assert by["App.Services.WhenDebug"]["display_kind"] == "class"
    assert by["App.Services.WhenElse"]["display_kind"] == "class"
    names = {pair[1] for pair in facts["types"]}
    assert "Hidden" not in names
    assert {"Widget", "Point", "WhenDebug", "WhenElse"} <= names
    assert facts["usings"] == ["Global.Ns", "Other.Ns"]
    assert facts["aliases"] == [["Alias", "App.Widget"]]
    assert "System.Math" in facts["type_refs"]
    assert "IList" in facts["type_refs"]
    assert "T" not in facts["type_refs"] and "U" not in facts["type_refs"]
    assert facts["imports"] == []
    run = "App.Services.Widget.Run"
    assert (run, "this", "Helper", None) in _calls(defs, facts)
    assert (run, "this", "Go", None) in _calls(defs, facts)
    assert (run, "member", "Store", "Save") in _calls(defs, facts)
    assert (run, "member", "Clock", "Tick") in _calls(defs, facts)
    assert (run, "member", "Environment", "GetEnvironmentVariable") in _calls(defs, facts)
    uses = [(_qual(defs, src), field, typ, method) for src, _cls, field, typ, method in facts["uses"]]
    assert ("App.Services.Widget.Run", "clock", "IClock", "Now") in uses
    assert ("App.Services.Primary.Go", "widget", "IClock", "Do") in uses
    envs = [(_qual(defs, src), name, default) for src, name, default in facts["envs"]]
    assert (run, "CONN", "c") in envs
    assert (run, "API_KEY", "none") in envs
    fields = {(defs[index]["qualname"], name, typ) for index, name, typ, _param, _i in facts["fields"]}
    assert ("App.Services.Widget", "clock", "IClock") in fields
    assert ("App.Services.Primary", "widget", "IClock") in fields


def test_csharp_test_attributes_and_parse_error():
    defs, _facts, err = _parse(TESTS, is_test=False)
    assert not err
    cases = [d for d in defs if d["kind"] == "test"]
    assert [d["name"] for d in cases] == ["A", "B", "C", "D", "E"]
    assert {d["display_kind"] for d in cases} == {"test case"}
    assert all(d["qualname"].startswith("Cases.") for d in cases)
    _defs, _facts, bad = _parse("class {\n")
    assert bad


def dump(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    lines = [json.dumps(["node", *r]) for r in conn.execute(
        "SELECT id, parent_id, kind, display_kind, start_line, end_line, signature, doc "
        "FROM nodes WHERE kind IN ('symbol', 'test') ORDER BY id")]
    lines += [json.dumps(["edge", *r]) for r in conn.execute(
        "SELECT kind, source, src, dst, confidence, weight FROM edges ORDER BY kind, source, src, dst")]
    lines += [json.dumps(["diagnostic", *r]) for r in conn.execute(
        "SELECT kind, node_id, detail FROM diagnostics ORDER BY kind, node_id")]
    return "".join(line + "\n" for line in lines)


def _db(root):
    return sqlite3.connect(root / ".cbi" / "model.db")


def _short(node_id):
    return node_id.split(":", 2)[-1]


def _calls_edges(conn):
    found = {}
    for src, dst, conf, weight, attrs in conn.execute(
            "SELECT s.id, d.id, e.confidence, e.weight, e.attrs FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.kind = 'calls'"):
        found[(_short(src).split("#", 1)[-1], _short(dst).split("#", 1)[-1])] = (
            conf, weight, json.loads(attrs) if attrs else None)
    return found


def _import_edges(conn):
    found = {}
    for src, dst, conf, attrs in conn.execute(
            "SELECT s.id, d.id, e.confidence, e.attrs FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.kind = 'imports'"):
        found[(_short(src), _short(dst))] = (conf, json.loads(attrs) if attrs else None)
    return found


@pytest.fixture
def repo(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    return root


def test_csharp_resolution(repo):
    conn = _db(repo)
    calls = _calls_edges(conn)
    inject = {"via": "injection"}

    def one(src, dst, confidence, attrs=None, weight=1):
        assert (src, dst) in calls, sorted(calls)
        got_conf, got_weight, got_attrs = calls[(src, dst)]
        assert got_conf == pytest.approx(confidence)
        assert got_weight == weight and got_attrs == attrs

    one("App.Services.Widget.Run", "App.Services.Widget.Helper", 0.6)
    one("App.Services.Widget.Run", "App.Services.Widget.Go", 0.6)
    one("App.Child.Run", "App.Store.Save", 1.0)
    one("App.Child.Run", "App.Clock.Tick", 1.0)
    one("App.Services.ViaGlobal.Go", "Other.Thing.Ping", 1.0)
    one("App.Services.ViaGlobal.Go", "App.Services.Widget.Extra", 1.0)
    one("Elsewhere.UsesAlias.Go", "App.Services.Widget.Extra", 1.0)
    one("App.Services.Widget.Run", "App.SystemClock.Now", 0.4, inject)
    one("App.Box.Save", "App.ConsoleLogger.Write", 0.4, inject)
    one("App.Holder.Bump", "App.Counter.Inc", 0.6, inject)
    one("App.Tests.WidgetTests.Run_writes", "App.Services.Widget.Run", 1.0)
    one("App.Tests.WidgetTests.Run_writes", "App.SystemClock", 1.0)
    assert not any("Pick" in dst for _src, dst in calls)

    imports = _import_edges(conn)
    # A csproj `<Using Include="Other"/>` links a file only when that file names a type Other declares.
    assert ("App/Widget.cs", "Other/Thing.cs") not in imports
    assert imports[("App/ViaGlobal.cs", "Other/Thing.cs")] == (pytest.approx(1.0), None)
    assert imports[("Elsewhere/Mentions.cs", "App/IClock.cs")] == (
        pytest.approx(0.4), {"type_ref": True})
    assert imports[("App/UsesAlias.cs", "App/Widget.cs")][0] == pytest.approx(0.4)
    assert imports[("App/UsesAlias.cs", "App/Widget.cs")][1] == {"type_ref": True}

    envs = {
        (dst.split(":env:", 1)[1], json.loads(attrs)["default"] if attrs else None)
        for dst, attrs in conn.execute(
            "SELECT dst, attrs FROM edges WHERE kind = 'reads_env' AND src LIKE '%Widget.cs#%'")
    }
    assert ("CONN", "c") in envs
    assert ("API_KEY", "none") in envs

    roles = {path: (kind, role) for path, kind, role in conn.execute(
        "SELECT path, display_kind, json_extract(attrs, '$.role') FROM nodes WHERE kind = 'file'")}
    assert roles["App.Tests/Helper.cs"] == ("test file", "test")
    assert roles["App/Sneaky.cs"] == ("test file", "test")
    assert roles["App/Widget.cs"] == ("source file", "code")
    assert roles["Lib/Lib.cs"] == ("source file", "code")

    nodes = { _short(i): (k, d, doc) for i, k, d, doc in conn.execute(
        "SELECT id, kind, display_kind, doc FROM nodes WHERE kind IN ('symbol', 'test')")}
    assert nodes["App/Widget.cs#App.Services.Widget"] == ("symbol", "class", "A widget.")
    assert nodes["App/Box.cs#App.Box.logger"][1] == "property"
    assert any(i.startswith("App/Widget.cs#App.Services.Widget.Pick~") for i in nodes)
    assert nodes["App.Tests/WidgetTests.cs#App.Tests.WidgetTests.Run_writes"][0] == "test"
    assert nodes["App.Tests/WidgetTests.cs#App.Tests.WidgetTests.NUnitOne"][1] == "test case"
    assert nodes["App.Tests/WidgetTests.cs#App.Tests.WidgetTests.MsOne"][1] == "test case"
    assert nodes["App/Sneaky.cs#App.Sneaky.Hidden"][0] == "test"

    tests = [( _short(s), _short(d), source, conf) for s, d, source, conf in conn.execute(
        "SELECT src, dst, source, confidence FROM edges WHERE kind = 'tests'")]
    naming = [row for row in tests if row[:3] == ("App.Tests/WidgetTests.cs", "App/Widget.cs", "naming")]
    assert len(naming) == 1 and naming[0][3] == pytest.approx(0.8)
    assert any(
        s.endswith("Run_writes") and d.endswith("App.Services.Widget.Run") and source == "treesitter"
        for s, d, source, _conf in tests)

    packages = {name: kind for name, kind in conn.execute(
        "SELECT name, display_kind FROM nodes WHERE kind = 'package'")}
    assert packages["App"] == "package"
    assert packages["Lib"] == "package"
    assert packages["Other"] == "package"
    assert packages["App.Tests"] == "package"
    assert packages["Lonely.Tests"] == "package"
    assert packages["App-sln"] == "solution"
    assert "Solution Items" not in packages

    deployables = {name: (kind, json.loads(attrs)["entry_points"]) for name, kind, attrs in conn.execute(
        "SELECT name, display_kind, attrs FROM nodes WHERE kind = 'deployable'")}
    assert deployables["App"] == ("web app", ["App/Program.cs"])
    assert deployables["Cli"] == ("program", ["Cli/Program.cs"])
    assert deployables["Tools"] == ("program", ["Tools/Program.cs"])
    assert deployables["Gap"] == ("web app", [])
    assert deployables["Both"] == ("web app", ["Both/Program.cs"])
    assert "App.Tests" not in deployables and "Lib" not in deployables

    depends = {(s.split(":")[-1], d.split(":")[-1]) for s, d in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'depends_on' AND src LIKE '%:package:%'")}
    assert ("App", "Lib") in depends
    assert ("App.Tests", "App") in depends
    assert ("App-sln", "App") in depends and ("App-sln", "Lib") in depends

    part = [d for (d,) in conn.execute(
        "SELECT dst FROM edges WHERE kind = 'part_of' AND src = ? AND dst LIKE '%:package:%'",
        (f"{WS}:App/Widget.cs",))]
    assert part == [f"{WS}:package:App"]

    unmatched = [path for (path,) in conn.execute(
        "SELECT n.path FROM diagnostics d JOIN nodes n ON n.id = d.node_id "
        "WHERE d.kind = 'unmatched_test' ORDER BY n.path")]
    # A test file whose usings name no type it mentions is unmatched. The namespace still exists.
    assert unmatched == [
        "App.Tests/Helper.cs",
        "App/Sneaky.cs",
        "Lonely.Tests/LonelyTests.cs",
    ]
    detail = conn.execute(
        "SELECT detail FROM diagnostics d JOIN nodes n ON n.id = d.node_id "
        "WHERE d.kind = 'unmatched_test' AND n.path = 'Lonely.Tests/LonelyTests.cs'").fetchone()[0]
    assert "Missing.Ns" in detail
    ambiguous = [path for (path,) in conn.execute(
        "SELECT n.path FROM diagnostics d JOIN nodes n ON n.id = d.node_id WHERE d.kind = 'ambiguous_call'")]
    assert ambiguous == ["App/Widget.cs"]
    parse_errors = [path for (path,) in conn.execute(
        "SELECT n.path FROM diagnostics d JOIN nodes n ON n.id = d.node_id WHERE d.kind = 'parse_error'")]
    assert parse_errors == ["Bad.cs"]
    gap = conn.execute(
        "SELECT detail FROM diagnostics WHERE kind = 'unresolved_entry' AND node_id = ?",
        (f"{WS}:deployable:Gap",)).fetchone()[0]
    assert "Program.cs" in gap


def test_testing_project_is_not_a_production_injection_candidate(make_repo, monkeypatch, capsys):
    """A `*.Testing.csproj` holds test helpers. Its classes are not production DI candidates."""
    root = make_repo({
        "App/App.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "App/Caller.cs": """\
namespace App;

public interface IPort
{
    void Send();
}

public class RealPort : IPort
{
    public void Send() {}
}

public record Caller(IPort port)
{
    public void Go()
    {
        port.Send();
    }
}
""",
        "Support.Testing/Support.Testing.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Support.Testing/Fakes.cs": """\
namespace Support.Testing;

public class FakePort : App.IPort
{
    public void Send() {}
}
""",
    }, name="testing-role")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = _db(root)
    role = conn.execute(
        "SELECT json_extract(attrs, '$.role') FROM nodes WHERE path = 'Support.Testing/Fakes.cs'"
    ).fetchone()[0]
    assert role == "test"
    calls = _calls_edges(conn)
    assert ("App.Caller.Go", "App.RealPort.Send") in calls
    assert calls[("App.Caller.Go", "App.RealPort.Send")][0] == pytest.approx(0.4)
    assert not any(dst.endswith("FakePort.Send") for _src, dst in calls)


def test_fromservices_factories_usings_and_config_reads(make_repo, monkeypatch, capsys):
    """Parameter injection, local factories, namespace usings and configuration reads."""
    root = make_repo({
        "Api/Api.csproj": """\
<Project Sdk="Microsoft.NET.Sdk.Web">
  <ItemGroup>
    <Using Include="Api" />
  </ItemGroup>
</Project>
""",
        "Api/Clock.cs": """\
namespace Api;

public interface IClock
{
    string Now();
}

public class SystemClock : IClock
{
    public string Now() => "t";
}
""",
        "Api/Handlers.cs": """\
namespace Api;

public class SaveItemHandler
{
    public void Handle(int id) {}
}

public class OtherHandler
{
    public void Handle() {}
}

public interface IPartnerClient
{
    string SendCode(string code);
}

public class PartnerClient : IPartnerClient
{
    public string SendCode(string code) => code;
}

public class RecordHandler
{
    public void Handle(int id) {}
}

public class AdjustHandler
{
    public void Handle(int id) {}
}
""",
        "Api/Controller.cs": """\
namespace Api;

public class ItemsController
{
    public void Save(int itemId, [FromServices] SaveItemHandler handler)
    {
        handler.Handle(itemId);
    }

    public void Send([FromServicesAttribute] IPartnerClient client)
    {
        client.SendCode("a");
    }
}

public class Primary(IClock clock)
{
    public void Go()
    {
        clock.Now();
    }
}

public class Auth(IConfiguration config)
{
    public void SignIn()
    {
        if (!config.GetValue<bool>("FEATURE_SIGN_IN")) return;
        var section = config.GetSection("FEATURE_REPORT_VIEW");
    }
}

public class Flags
{
    public Flags(IConfiguration config)
        : this(config.GetValue<bool>("TESTING_ENDPOINTS"))
    {
    }

    public Flags(bool on) {}
}
""",
        "Api/Program.cs": """\
using Api.Data;

var connectionString = builder.Configuration.GetConnectionString("SampleApp");
var url = builder.Configuration["PARTNER_API_URL"] ?? "http://localhost:5090";
if (services.GetRequiredService<IConfiguration>().GetValue<bool>("FEATURE_SIGN_IN")) return;
app.MapGet("/health", async (SampleAppDb db) => await db.Database.CanConnectAsync());
app.MapPost("/tick", (IClock clock) => clock.Now());
""",
        "Api/Data/SampleAppDb.cs": """\
namespace Api.Data;

public class SampleAppDb
{
    public static void Migrate() {}
}
""",
        "Api/Data/DesignTimeDbFactory.cs": """\
namespace Api.Data;

public class DesignTimeDbFactory
{
    public void Create() {}
}
""",
        "Api/UsesDb.cs": """\
using Api.Data;

namespace Api;

public class UsesDb
{
    public void Go()
    {
        SampleAppDb.Migrate();
    }
}
""",
        "Api/UnusedUsing.cs": """\
using Api.Data;

namespace Api;

public class UnusedUsing
{
    public void Go() {}
}
""",
        "Api/LocalDatabase.cs": """\
namespace Api;

public static class LocalDatabase
{
    public static string FromDotEnv(string root)
    {
        var envFile = Path.Combine(root, ".env");
        return envFile;
    }

    public static string FromLines()
    {
        if (!settings.TryGetValue("DB_PASSWORD", out var password)) return "";
        return settings.GetValueOrDefault("DB_PORT", "14330");
    }
}
""",
        "Api/NotDotEnv.cs": """\
namespace Api;

public class NotDotEnv
{
    public void M()
    {
        throw new InvalidOperationException("copy .env.example to .env in sample-app/.");
        settings.TryGetValue("DB_PASSWORD", out var password);
        Users.TryGetValue(request.Role, out var user);
    }
}
""",
        "Api.Tests/Api.Tests.csproj": """\
<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <ProjectReference Include="../Api/Api.csproj" />
  </ItemGroup>
</Project>
""",
        "Api.Tests/SaveItemHandlerTests.cs": """\
using Api;

namespace Api.Tests;

public class SaveItemHandlerTests
{
    private SaveItemHandler Handler() => new SaveItemHandler();

    [Fact]
    public void Saves_one_item()
    {
        Handler().Handle(1);
    }
}
""",
        "Api.Tests/PartnerClientTests.cs": """\
using Api;

namespace Api.Tests;

public class PartnerClientTests
{
    private static PartnerClient ClientThatThrows(Exception error) => new PartnerClient();

    [Fact]
    public void Send_throws()
    {
        ClientThatThrows(new Exception()).SendCode("abc");
    }
}
""",
        "Api.Tests/LimitTests.cs": """\
using Api;

namespace Api.Tests;

public class LimitTests
{
    [Fact]
    public void A_value_cannot_exceed_the_limit()
    {
        new RecordHandler().Handle(1);
        new AdjustHandler().Handle(1);
    }
}
""",
        "Api.Tests/AmbiguousFactoryTests.cs": """\
using Api;

namespace Api.Tests;

public class AmbiguousFactoryTests
{
    private SaveItemHandler Make() => new SaveItemHandler();

    private OtherHandler Make(int n) => new OtherHandler();

    [Fact]
    public void Does_not_bind_every_handle()
    {
        Make().Handle();
    }
}
""",
    }, name="csharp-gaps")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = _db(root)
    calls = _calls_edges(conn)
    inject = {"via": "injection"}

    def call(src, dst):
        assert (src, dst) in calls, sorted(calls)
        return calls[(src, dst)]

    conf, _weight, attrs = call("Api.ItemsController.Save", "Api.SaveItemHandler.Handle")
    assert conf == pytest.approx(0.6) and attrs == inject
    conf, _weight, attrs = call("Api.ItemsController.Send", "Api.PartnerClient.SendCode")
    assert conf == pytest.approx(0.4) and attrs == inject
    conf, _weight, attrs = call("Api.Primary.Go", "Api.SystemClock.Now")
    assert conf == pytest.approx(0.4) and attrs == inject
    conf, _weight, attrs = call("Api/Program.cs", "Api.SystemClock.Now")
    assert conf == pytest.approx(0.4) and attrs == inject
    assert not any("CanConnect" in dst or dst.endswith("Database") for _src, dst in calls)

    conf, _weight, attrs = call(
        "Api.Tests.SaveItemHandlerTests.Saves_one_item", "Api.SaveItemHandler.Handle")
    assert conf == pytest.approx(1.0) and attrs is None
    assert ("Api.Tests.SaveItemHandlerTests.Saves_one_item", "Api.OtherHandler.Handle") not in calls
    conf, _weight, attrs = call(
        "Api.Tests.PartnerClientTests.Send_throws", "Api.PartnerClient.SendCode")
    assert conf == pytest.approx(1.0) and attrs is None
    conf, _weight, _attrs = call(
        "Api.Tests.LimitTests.A_value_cannot_exceed_the_limit", "Api.RecordHandler.Handle")
    assert conf == pytest.approx(1.0)
    conf, _weight, _attrs = call(
        "Api.Tests.LimitTests.A_value_cannot_exceed_the_limit", "Api.AdjustHandler.Handle")
    assert conf == pytest.approx(1.0)
    credit = "Api.Tests.LimitTests.A_value_cannot_exceed_the_limit"
    assert (credit, "Api.OtherHandler.Handle") not in calls
    ambiguous = "Api.Tests.AmbiguousFactoryTests.Does_not_bind_every_handle"
    assert (ambiguous, "Api.SaveItemHandler.Handle") not in calls
    assert (ambiguous, "Api.OtherHandler.Handle") not in calls

    imports = _import_edges(conn)
    assert imports[("Api/UsesDb.cs", "Api/Data/SampleAppDb.cs")] == (pytest.approx(1.0), None)
    assert imports[("Api/Program.cs", "Api/Data/SampleAppDb.cs")] == (pytest.approx(1.0), None)
    assert ("Api/UsesDb.cs", "Api/Data/DesignTimeDbFactory.cs") not in imports
    assert ("Api/UnusedUsing.cs", "Api/Data/DesignTimeDbFactory.cs") not in imports
    assert ("Api/UnusedUsing.cs", "Api/Data/SampleAppDb.cs") not in imports
    assert ("Api/Program.cs", "Api/Data/DesignTimeDbFactory.cs") not in imports

    readers = {
        (path, name, dst.split(":env:")[-1], default)
        for path, name, dst, default in conn.execute(
            "SELECT s.path, s.name, e.dst, json_extract(e.attrs, '$.default') "
            "FROM edges e JOIN nodes s ON s.id = e.src WHERE e.kind = 'reads_env'")
    }
    assert ("Api/Controller.cs", "SignIn", "FEATURE_SIGN_IN", None) in readers
    assert ("Api/Controller.cs", "SignIn", "FEATURE_REPORT_VIEW", None) in readers
    assert ("Api/Controller.cs", "Flags", "TESTING_ENDPOINTS", None) in readers
    assert ("Api/Program.cs", "Program.cs", "ConnectionStrings__SampleApp", None) in readers
    assert ("Api/Program.cs", "Program.cs", "FEATURE_SIGN_IN", None) in readers
    assert ("Api/Program.cs", "Program.cs", "PARTNER_API_URL", "http://localhost:5090") in readers
    assert ("Api/LocalDatabase.cs", "FromLines", "DB_PASSWORD", None) in readers
    assert ("Api/LocalDatabase.cs", "FromLines", "DB_PORT", "14330") in readers
    assert not any(path == "Api/NotDotEnv.cs" for path, _name, _env, _default in readers)


def test_golden_csharp(repo):
    text = dump(repo)
    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()
