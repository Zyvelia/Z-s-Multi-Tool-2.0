"""Adapter registry — lookup game types by id."""



from __future__ import annotations



from .base import GameServerAdapter

from .games import (

    CustomServerAdapter,

    ProjectZomboidAdapter,

    SatisfactoryAdapter,

    SteamCmdAdapter,

    TerrariaAdapter,

    ValheimAdapter,

)

from .minecraft_bedrock import MinecraftBedrockAdapter

from .minecraft_java import MinecraftJavaAdapter

from .palworld import PalworldAdapter

from .steam_games import (

    GENERIC_STEAM_ADAPTERS,

    AbioticFactorAdapter,

    ArkAscendedAdapter,

    ArkEvolvedAdapter,

    AskaAdapter,

    AtlasAdapter,

    AvorionAdapter,

    BarotraumaAdapter,

    BannerlordAdapter,

    ConanExilesAdapter,

    CoreKeeperAdapter,

    CounterStrike2Adapter,

    GmodAdapter,

    L4d2Adapter,

    DayZAdapter,

    DontStarveTogetherAdapter,

    EcoAdapter,

    EmpyrionAdapter,

    EnshroudedAdapter,

    FactorioAdapter,

    HellLetLooseAdapter,

    HoldfastAdapter,

    HumanitzAdapter,

    IcarusAdapter,

    InsurgencySandstormAdapter,

    MordhauAdapter,

    NecesseAdapter,

    OnceHumanAdapter,

    PixarkAdapter,

    PostScriptumAdapter,

    RaftAdapter,

    RustAdapter,

    ScumAdapter,

    SevenDaysToDieAdapter,

    SmallandAdapter,

    SonsOfTheForestAdapter,

    SoulmaskAdapter,

    SpaceEngineersAdapter,

    SquadAdapter,

    StarboundAdapter,

    SunkenlandAdapter,

    TheForestAdapter,

    UnturnedAdapter,

    VRisingAdapter,

)



_ADAPTERS: dict[str, GameServerAdapter] = {}



_PRIORITY: dict[str, int] = {

    "minecraft_java": 0,

    "minecraft_bedrock": 1,

}





def _register(adapter: GameServerAdapter) -> None:

    _ADAPTERS[adapter.game_type] = adapter





def register_all() -> None:

    if _ADAPTERS:

        return

    for adapter in (

        MinecraftJavaAdapter(),

        MinecraftBedrockAdapter(),

        SatisfactoryAdapter(),

        TerrariaAdapter(),

        ValheimAdapter(),

        PalworldAdapter(),

        ProjectZomboidAdapter(),

        RustAdapter(),

        ArkEvolvedAdapter(),

        ArkAscendedAdapter(),

        PixarkAdapter(),

        AtlasAdapter(),

        CounterStrike2Adapter(),

        GmodAdapter(),

        L4d2Adapter(),

        SevenDaysToDieAdapter(),

        FactorioAdapter(),

        EnshroudedAdapter(),

        VRisingAdapter(),

        DayZAdapter(),

        SonsOfTheForestAdapter(),

        TheForestAdapter(),

        CoreKeeperAdapter(),

        SpaceEngineersAdapter(),

        ScumAdapter(),

        EcoAdapter(),

        NecesseAdapter(),

        RaftAdapter(),

        IcarusAdapter(),

        BarotraumaAdapter(),

        UnturnedAdapter(),

        EmpyrionAdapter(),

        AvorionAdapter(),

        SquadAdapter(),

        HellLetLooseAdapter(),

        PostScriptumAdapter(),

        AbioticFactorAdapter(),

        SunkenlandAdapter(),

        AskaAdapter(),

        BannerlordAdapter(),

        DontStarveTogetherAdapter(),

        HoldfastAdapter(),

        HumanitzAdapter(),

        InsurgencySandstormAdapter(),

        MordhauAdapter(),

        OnceHumanAdapter(),

        SmallandAdapter(),

        StarboundAdapter(),

        ConanExilesAdapter(),

        SoulmaskAdapter(),

        *GENERIC_STEAM_ADAPTERS,

        SteamCmdAdapter(),

        CustomServerAdapter(),

    ):

        _register(adapter)





def get_adapter(game_type: str) -> GameServerAdapter | None:

    register_all()

    return _ADAPTERS.get(game_type)





def all_adapters() -> list[GameServerAdapter]:

    register_all()

    return list(_ADAPTERS.values())





def _choice_sort_key(adapter: GameServerAdapter) -> tuple[int, str]:

    gt = adapter.game_type

    if gt in _PRIORITY:

        return _PRIORITY[gt], ""

    if gt in ("steamcmd", "custom"):

        return 900 if gt == "steamcmd" else 901, adapter.display_name.lower()

    return 10, adapter.display_name.lower()





def game_choices() -> list[tuple[str, str, str]]:

    """Return (game_type, display_name, icon) for wizard menus — sorted A–Z."""

    adapters = sorted(all_adapters(), key=_choice_sort_key)

    return [(a.game_type, a.display_name, a.icon) for a in adapters]

