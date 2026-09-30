"""Hermetic test for scripts/research/layout.py: it reads javap text, never runs Java."""

import importlib.util
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "layout.py"

_JAVAP = """\
Classfile /x/Things.class
Constant pool:
   #1 = Utf8               ignored line, three spaces in
  #341 = MethodHandle       6:#342  // REF_invokeStatic Things.lambda$static$0:(L;)V;
  public static final Thing ONE;
    descriptor: Lnet/minecraft/Thing;
  private static Builder lambda$static$0(Builder);
    descriptor: (Lnet/minecraft/Builder;)Lnet/minecraft/Builder;
    Code:
      stack=3, locals=1, args_size=1
         0: aload_0
         1: getstatic     #378   // Field net/minecraft/network/codec/ByteBufCodecs.VAR_INT:Lx;
         4: invokevirtual #57    // Method net/minecraft/Builder.sync:(Lx;)Lnet/minecraft/Builder;
         7: bipush        99
         9: areturn
      LineNumberTable:
        line 126: 0
  static {};
    Code:
         0: ldc_w         #519   // String custom_data
         3: invokedynamic #521,  0   // InvokeDynamic #1:apply:()Ljava/util/function/UnaryOperator;
         8: invokestatic  #524   // Method register:(Ljava/lang/String;)Lnet/minecraft/Thing;
        11: putstatic     #7     // Field ONE:Lnet/minecraft/Thing;
BootstrapMethods:
  0: #1918 REF_invokeStatic java/lang/invoke/LambdaMetafactory.metafactory:(L;)Ljava/lang/Object;
    Method arguments:
      #1550 (Ljava/lang/Object;)Ljava/lang/Object;
      #1551 REF_invokeStatic net/minecraft/Things.lambda$static$9:(Lnet/minecraft/Builder;)V
  1: #1918 REF_invokeStatic java/lang/invoke/LambdaMetafactory.metafactory:(L;)Ljava/lang/Object;
    Method arguments:
      #1550 (Ljava/lang/Object;)Ljava/lang/Object;
      #1555 REF_invokeVirtual net/minecraft/Things.name:()Ljava/lang/String;
"""


@pytest.fixture
def layout() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("layout", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prints_only_the_matching_methods_layout_and_resolves_lambdas(
    layout: types.ModuleType,
) -> None:
    lambda_body = [
        "METHOD private static Builder lambda$static$0(Builder);",
        "    getstatic Field network/codec/ByteBufCodecs.VAR_INT:Lx;",
        "    invokevirtual Method Builder.sync:(Lx;)LBuilder;",
        "    bipush 99",
    ]
    initializer = [
        "METHOD static {};",
        "    ldc_w String custom_data",
        "    invokedynamic -> REF_invokeVirtual Things.name",
        "    invokestatic Method register:(LString;)LThing;",
        "    putstatic Field ONE:LThing;",
    ]

    assert layout.layout(_JAVAP, r"lambda\$static\$0") == lambda_body
    assert layout.layout(_JAVAP, r"static \{\}") == initializer
    assert layout.layout(_JAVAP, "lambda|static") == lambda_body + initializer
    assert layout.layout(_JAVAP, "nothing matches this") == []
    everything = layout.layout(_JAVAP, r"lambda\$static\$0", show_all=True)
    assert "    aload_0" in everything
    assert "    areturn" in everything
