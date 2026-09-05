import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {Api, getBaseUrl, setBaseUrl} from './src/api';
import type {Analysis, Meeting, Race, Score} from './src/types';

type Tab = 'selections' | 'programme' | 'results' | 'stats' | 'settings';

const C = {
  bg: '#07090E',
  card: '#0E121A',
  raised: '#141923',
  line: '#232A36',
  lineSoft: '#191F2A',
  gold: '#D8B565',
  goldBright: '#F1D58D',
  goldDeep: '#8F7138',
  ivory: '#F5F1E8',
  text: '#E8E5DE',
  muted: '#8F96A3',
  mutedDark: '#646C79',
  green: '#79B99A',
  blue: '#6FA6C9',
  purple: '#A793D2',
  coral: '#D38A7A',
  red: '#FF9A9A',
};

const fmt = (iso: string) =>
  new Date(iso).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'});

const localISO = (offset = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`;
};

const longDate = (offset = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toLocaleDateString('fr-FR', {weekday: 'long', day: 'numeric', month: 'long'});
};

const plainLabel = (value?: string | null) => {
  if (!value) return '';
  const labels: Record<string, string> = {
    COURSE_A_CONDITIONS: 'Course à conditions',
    COURSE_A_RECLAMER: 'Course à réclamer',
    HANDICAP_DIVISE: 'Handicap divisé',
    FEMELLES: 'Femelle',
    MALES: 'Mâle',
    HONGRES: 'Hongre',
    SANS_OEILLERES: 'Sans œillères',
    AVEC_OEILLERES: 'Avec œillères',
    OEILLERES_AUSTRALIENNES: 'Œillères australiennes',
    HERBE: 'Herbe',
    GAZON: 'Gazon',
    SABLE_FIBRE: 'Piste en sable fibré',
    PISTE_EN_SABLE_FIBRE: 'Piste en sable fibré',
  };
  const key = value.trim().toUpperCase().replace(/ /g, '_');
  if (labels[key]) return labels[key];
  if (value.includes('_') || value === value.toUpperCase()) {
    const lower = value.replace(/_/g, ' ').toLocaleLowerCase('fr-FR');
    return lower.charAt(0).toLocaleUpperCase('fr-FR') + lower.slice(1);
  }
  return value;
};

const scoreIsRankable = (score: Score) => score.breakdown?.ranking_eligible === true;

type OpponentNetwork = {
  score?: number;
  eligible?: boolean;
  paragraph?: string;
  history_rows?: number;
  linked_races?: number;
  coverage_percent?: number;
  direct_rivals?: number;
  direct_comparisons?: number;
  direct_wins?: number;
  confirmed_lines?: number;
  higher_or_equal_confirmations?: number;
  indirect_chains?: number;
  second_degree_chains?: number;
  third_degree_chains?: number;
  previous_meetings_today?: number;
  today_opponent_bridges?: number;
  bridge_supports?: number;
  bridge_counter_signals?: number;
  today_bridge_examples?: string[];
  chain_examples?: string[];
  independent?: boolean;
};

const opponentNetwork = (score: Score): OpponentNetwork | null => {
  const value = score.breakdown?.opponent_network;
  return value && typeof value === 'object' ? (value as OpponentNetwork) : null;
};

function normalizeMeetings(payload: unknown): Meeting[] {
  if (Array.isArray(payload)) return payload as Meeting[];
  if (!payload || typeof payload !== 'object') return [];
  const value = payload as {meetings?: unknown; data?: {meetings?: unknown}};
  if (Array.isArray(value.meetings)) return value.meetings as Meeting[];
  if (Array.isArray(value.data?.meetings)) return value.data.meetings as Meeting[];
  return [];
}

function Logo() {
  return (
    <View style={s.logo}>
      <Text style={s.logoText}>HE</Text>
      <View style={s.logoDot} />
    </View>
  );
}

function Eyebrow({children}: {children: React.ReactNode}) {
  return <Text style={s.eyebrow}>{children}</Text>;
}

function Pill({children, gold = false}: {children: React.ReactNode; gold?: boolean}) {
  return (
    <View style={[s.pill, gold && s.pillGold]}>
      <Text style={[s.pillText, gold && s.pillTextGold]}>{children}</Text>
    </View>
  );
}

function Section({eyebrow, title, text}: {eyebrow: string; title: string; text?: string}) {
  return (
    <View style={s.sectionHead}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <Text style={s.sectionTitle}>{title}</Text>
      {!!text && <Text style={s.sectionText}>{text}</Text>}
    </View>
  );
}

function ScoreBadge({label, value, color}: {label: string; value: number; color: string}) {
  return (
    <View style={s.scoreBadge}>
      <View style={[s.scoreDot, {backgroundColor: color}]} />
      <Text style={s.scoreLabel}>{label}</Text>
      <Text style={[s.scoreValue, {color}]}>{Math.round(value)}</Text>
    </View>
  );
}

type EvidenceQuality = {
  total?: number;
  ready?: number;
  ready_percent?: number;
  complete?: number;
  partial?: number;
  limited?: number;
  loading?: number;
  insufficient?: number;
  ranking_eligible?: number;
  status?: string;
  historical_race_rows?: number;
  historical_race_rows_linked?: number;
  historical_race_rows_pending?: number;
  historical_race_link_percent?: number;
};

function qualityCopy(quality: EvidenceQuality, scope: 'day' | 'race') {
  const total = Number(quality.total || 0);
  const ready = Number(quality.ready || 0);
  const eligible = Number(quality.ranking_eligible || 0);
  const loading = Number(quality.loading || 0);
  const incomplete = Number(quality.insufficient || 0);
  if (!total) {
    return scope === 'day'
      ? 'Les courses sont chargées ; le contrôle des historiques va commencer.'
      : 'Les partants sont chargés ; le contrôle de leurs historiques va commencer.';
  }
  if (loading > 0) {
    return `${ready} sur ${total} dossier${total > 1 ? 's' : ''} ${ready === 1 ? 'est' : 'sont'} exploitable${ready === 1 ? '' : 's'}. ${loading} historique${loading > 1 ? 's' : ''} ${loading > 1 ? 'restent' : 'reste'} en cours de vérification.`;
  }
  if (eligible === 0) {
    return 'Aucun rang public n’est publié : les preuves disponibles ne permettent pas encore une comparaison sérieuse.';
  }
  if (incomplete > 0) {
    return `${eligible} cheval${eligible > 1 ? 'aux' : ''} peut${eligible > 1 ? 'vent' : ''} être classé${eligible > 1 ? 's' : ''}. ${incomplete} dossier${incomplete > 1 ? 's' : ''} reste${incomplete > 1 ? 'nt' : ''} trop incomplet${incomplete > 1 ? 's' : ''} pour être recommandé.`;
  }
  return `${eligible} cheval${eligible > 1 ? 'aux' : ''} dispose${eligible > 1 ? 'nt' : ''} d’une base suffisante pour la hiérarchie publiée.`;
}

function DataQualityCard({quality}: {quality: EvidenceQuality}) {
  const percent = Math.max(0, Math.min(100, Number(quality.ready_percent || 0)));
  const loading = Number(quality.loading || 0) > 0;
  const eligible = Number(quality.ranking_eligible || 0);
  const historicalTotal = Number(quality.historical_race_rows || 0);
  const historicalLinked = Number(quality.historical_race_rows_linked || 0);
  const historicalPending = Number(quality.historical_race_rows_pending || 0);
  return (
    <View style={s.qualityCard}>
      <View style={s.qualityHead}>
        <View style={s.qualityIcon}><Text style={s.qualityIconText}>{loading ? '…' : '✓'}</Text></View>
        <View style={{flex: 1}}>
          <Text style={s.qualityKicker}>CONTRÔLE DES DOSSIERS</Text>
          <Text style={s.qualityTitle}>{loading ? 'Analyse en préparation' : eligible ? 'Base de comparaison prête' : 'Lecture encore incomplète'}</Text>
        </View>
        <Text style={s.qualityPercent}>{percent}%</Text>
      </View>
      <View style={s.qualityTrack}><View style={[s.qualityFill, {width: `${percent}%`}]} /></View>
      <Text style={s.qualityText}>{qualityCopy(quality, 'day')}</Text>
      {historicalTotal > 0 && (
        <Text style={s.qualityFoot}>
          Réseau historique : {historicalLinked} sur {historicalTotal} ancienne{historicalTotal > 1 ? 's' : ''} course{historicalTotal > 1 ? 's' : ''} recroisée{historicalTotal > 1 ? 's' : ''}
          {historicalPending > 0 ? ` · ${historicalPending} en cours` : ' · contrôle terminé'}.
        </Text>
      )}
      <Text style={s.qualityFoot}>Les chevaux sans preuves suffisantes restent visibles, mais ne sont jamais transformés en choix.</Text>
    </View>
  );
}

function AnalysisQuality({quality}: {quality: EvidenceQuality}) {
  const loading = Number(quality.loading || 0) > 0;
  const eligible = Number(quality.ranking_eligible || 0);
  return (
    <View style={s.analysisQuality}>
      <View style={s.analysisQualityHead}>
        <Text style={s.analysisQualityTitle}>Fiabilité de cette lecture</Text>
        <View style={[s.evidenceBadge, loading ? s.evidenceLoading : eligible ? s.evidenceReady : s.evidenceLimited]}>
          <Text style={[s.evidenceBadgeText, loading ? s.evidenceLoadingText : eligible ? s.evidenceReadyText : s.evidenceLimitedText]}>
            {loading ? 'EN COURS' : eligible ? 'COMPARABLE' : 'LIMITÉE'}
          </Text>
        </View>
      </View>
      <Text style={s.analysisQualityText}>{qualityCopy(quality, 'race')}</Text>
      <Text style={s.analysisQualityFoot}>Un score affiché n’est un classement que si le dossier porte le badge « base exploitable ».</Text>
    </View>
  );
}

function AnalysisGuide() {
  return (
    <View style={s.guideCard}>
      <Text style={s.guideTitle}>Comment lire les repères</Text>
      <Text style={s.guideText}>
        <Text style={s.guideStrong}>Performance</Text> : capacité à viser la victoire dans ce lot.{' '}
        <Text style={s.guideStrong}>Placé</Text> : chance de rester dans les places avec plusieurs scénarios.{' '}
        <Text style={s.guideStrong}>Caché</Text> : valeur qui peut être meilleure que la forme récente.{' '}
        <Text style={s.guideStrong}>Robuste</Text> : résistance aux aléas de course.{' '}
        <Text style={s.guideStrong}>Volatilité</Text> : risque d’une prévision moins sûre ; plus elle est haute, plus il faut rester prudent.{' '}
        <Text style={s.guideStrong}>Réseau</Text> : classement séparé construit avec les adversaires réellement croisés et leurs résultats suivants ; il ne change aucune autre note.{' '}
        <Text style={s.guideStrong}>Finisseur</Text> : capacité répétée à gagner des places ou produire un meilleur dernier tronçon dans la phase finale, uniquement à partir de déroulements/sectionnels factuels.{' '}
        <Text style={s.guideStrong}>Résistance aux finisseurs</Text> : preuve qu’un cheval a déjà conservé l’avantage sur un finisseur du lot précisément pendant une course où le finish de ce rival était objectivement mesuré.{' '}
        <Text style={s.guideStrong}>Progressif tardif</Text> : cheval qui remonte avant la toute dernière phase puis soutient cet effort jusqu’au poteau. Les notes /100 restent visibles, mais les arguments factuels sont prioritaires.
      </Text>
    </View>
  );
}

function EvidenceBadge({status, label, rankable}: {status: string; label?: string; rankable: boolean}) {
  const loading = status === 'loading';
  const ready = rankable;
  const text = loading ? 'Vérification en cours' : ready ? (label || 'Base exploitable') : status === 'insufficient' ? 'Preuves insuffisantes' : (label || 'Lecture partielle');
  return (
    <View style={[s.evidenceBadge, loading ? s.evidenceLoading : ready ? s.evidenceReady : s.evidenceLimited]}>
      <View style={[s.evidenceDot, {backgroundColor: loading ? C.gold : ready ? C.green : C.coral}]} />
      <Text style={[s.evidenceBadgeText, loading ? s.evidenceLoadingText : ready ? s.evidenceReadyText : s.evidenceLimitedText]}>{text}</Text>
    </View>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>('selections');
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selected, setSelected] = useState<Race | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState<any>(null);
  const [dashboard, setDashboard] = useState<any>(null);
  const [url, setUrl] = useState('');
  const [health, setHealth] = useState<any>(null);
  const [dayOffset, setDayOffset] = useState<0 | 1>(0);
  const [selections, setSelections] = useState<any>(null);
  const [selectionRunning, setSelectionRunning] = useState(false);
  const raceAbortRef = useRef<AbortController | null>(null);
  const selectionAbortRef = useRef<AbortController | null>(null);
  const dashboardByDayRef = useRef<Record<string, any>>({});

  function applyDashboard(day: string, next: any) {
    if (!next) return;
    const previous = dashboardByDayRef.current[day];
    const previousActivity = previous?.activity || {};
    const nextActivity = next?.activity || {};
    const merged = previous ? {
      ...next,
      ready_race_ids: Array.from(new Set([
        ...((previous?.ready_race_ids || []) as number[]),
        ...((next?.ready_race_ids || []) as number[]),
      ])),
      activity: {
        ...nextActivity,
        // These values describe persistent historical facts and therefore must
        // never visually go backwards because an older HTTP response arrives
        // after a newer one. Totals may only grow as new profiles are found.
        historical_unique_courses_linked: Math.max(
          Number(previousActivity.historical_unique_courses_linked || 0),
          Number(nextActivity.historical_unique_courses_linked || 0),
        ),
        historical_unique_courses_total: Math.max(
          Number(previousActivity.historical_unique_courses_total || 0),
          Number(nextActivity.historical_unique_courses_total || 0),
        ),
        cached_historical_races_global: Math.max(
          Number(previousActivity.cached_historical_races_global || 0),
          Number(nextActivity.cached_historical_races_global || 0),
        ),
      },
    } : next;
    dashboardByDayRef.current[day] = merged;
    setDashboard(merged);
  }

  useEffect(() => {
    getBaseUrl().then(setUrl);
    loadProgram();
    return () => {
      raceAbortRef.current?.abort();
      selectionAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(async () => {
      const day = localISO(dayOffset);
      try {
        const dash = await Api.dashboard(day);
        applyDashboard(day, dash);
        if (Number(dash?.activity?.courses_analyzed || 0) > 0) {
          const picks = await Api.selections(day).catch(() => null);
          if (picks) setSelections(picks);
        }
      } catch {
        // Keep the last known UI state; the normal refresh/error path remains explicit.
      }
    }, 30000);
    return () => clearInterval(timer);
  }, [dayOffset]);

  useEffect(() => {
    let lastReadyCount = -1;
    const timer = setInterval(async () => {
      const day = localISO(dayOffset);
      try {
        const queue = await Api.queue(day);
        const previous = dashboardByDayRef.current[day];
        if (previous) {
          const updated = {
            ...previous,
            ready: queue.ready,
            status: queue.ready ? 'ready' : 'updating',
            ready_race_ids: queue.ready_race_ids || [],
            pending_race_ids: queue.pending_race_ids || [],
            next_pending_race: queue.next_pending_race || null,
            race_queue: queue.race_queue || [],
            activity: {
              ...(previous.activity || {}),
              courses_total: queue.courses_total || 0,
              courses_analyzed: queue.courses_analyzed || 0,
              courses_updating: queue.courses_updating || 0,
              courses_missed_without_prerace: queue.courses_missed_without_prerace || 0,
            },
          };
          dashboardByDayRef.current[day] = updated;
          setDashboard(updated);
        }
        const count = Number(queue?.courses_analyzed || 0);
        if (count > 0 && count !== lastReadyCount) {
          lastReadyCount = count;
          const picks = await Api.selections(day).catch(() => null);
          if (picks) setSelections(picks);
        }
      } catch {
        // Lightweight queue polling is best-effort; the 30 s dashboard refresh remains authoritative.
      }
    }, 5000);
    return () => clearInterval(timer);
  }, [dayOffset]);

  async function loadProgram(offset: 0 | 1 = dayOffset) {
    setLoading(true);
    setError('');
    const day = localISO(offset);
    try {
      const [program, dash, picks] = await Promise.all([
        Api.program(day),
        Api.dashboard(day).catch(() => null),
        Api.selections(day).catch(() => null),
      ]);
      setMeetings(normalizeMeetings(program));
      applyDashboard(day, dash);
      setSelections(picks);
    } catch (e: any) {
      setMeetings([]);
      setError(`Programme : ${e?.message || String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  async function chooseDay(offset: 0 | 1) {
    selectionAbortRef.current?.abort();
    selectionAbortRef.current = null;
    setSelections(null);
    setSelectionRunning(false);
    setDayOffset(offset);
    await loadProgram(offset);
  }

  async function refresh() {
    selectionAbortRef.current?.abort();
    selectionAbortRef.current = null;
    setLoading(true);
    setError('');
    const day = localISO(dayOffset);
    try {
      await Api.refresh(day);
      const [program, dash, picks] = await Promise.all([
        Api.program(day),
        Api.dashboard(day).catch(() => null),
        Api.selections(day).catch(() => null),
      ]);
      setMeetings(normalizeMeetings(program));
      applyDashboard(day, dash);
      setSelections(picks);
    } catch (e: any) {
      setError(`Actualisation : ${e?.message || String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  async function openRace(race: Race) {
    raceAbortRef.current?.abort();
    raceAbortRef.current = null;
    setSelected(race);
    setAnalysis(null);
    setLoading(true);
    setError('');
    try {
      // Read the already-prepared snapshot only. Heavy data collection and
      // scoring are handled continuously by the backend preload worker.
      const loaded = await Api.analysis(race.id);
      setAnalysis(loaded);
      if (loaded.result && !race.result) {
        setSelected({...race, result: loaded.result});
      }
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runSelections() {
    selectionAbortRef.current?.abort();
    selectionAbortRef.current = null;
    setSelectionRunning(true);
    setLoading(true);
    setError('');
    const day = localISO(dayOffset);
    try {
      const [picks, dash] = await Promise.all([
        Api.selections(day),
        Api.dashboard(day).catch(() => null),
      ]);
      setSelections(picks);
      applyDashboard(day, dash);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setSelectionRunning(false);
      setLoading(false);
    }
  }

  function switchTab(next: Tab) {
    setError('');
    setTab(next);
  }

  async function lock() {
    if (!selected) return;
    try {
      await Api.lock(selected.id);
      setAnalysis(await Api.analysis(selected.id));
      Alert.alert(
        'Analyse figée',
        'Le snapshot pré-course est verrouillé et ne sera jamais réécrit après l’arrivée.',
      );
    } catch (e: any) {
      Alert.alert('Erreur', e.message);
    }
  }

  async function loadStats() {
    switchTab('stats');
    try {
      const [performanceStats, dash] = await Promise.all([
        Api.stats(),
        Api.dashboard(localISO(dayOffset)),
      ]);
      setStats(performanceStats);
      applyDashboard(localISO(dayOffset), dash);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function saveSettings() {
    await setBaseUrl(url);
    try {
      const result = await Api.health();
      setHealth(result);
      Alert.alert('Connexion OK', `${result.app} • ${result.provider}`);
    } catch (e: any) {
      setHealth(null);
      Alert.alert('Connexion impossible', e.message);
    }
  }

  if (selected) {
    return (
      <RaceView
        race={selected}
        analysis={analysis}
        loading={loading}
        error={error}
        onBack={() => {
          raceAbortRef.current?.abort();
          raceAbortRef.current = null;
          setSelected(null);
          setAnalysis(null);
          setLoading(false);
          setError('');
        }}
        onRefresh={() => openRace(selected)}
        onLock={lock}
      />
    );
  }

  return (
    <SafeAreaView style={s.safe}>
      <StatusBar barStyle="light-content" backgroundColor={C.bg} />
      <View style={s.header}>
        <View style={s.brandRow}>
          <Logo />
          <View>
            <Text style={s.brand}>HippoEdge</Text>
            <Text style={s.subtitle}>Intelligence hippique indépendante</Text>
          </View>
        </View>
        <View style={s.livePill}>
          <View style={s.liveDot} />
          <Text style={s.liveText}>LIVE</Text>
        </View>
      </View>

      <View style={s.screen}>
        {tab === 'selections' && (
          <SelectionsScreen
            dayOffset={dayOffset}
            selections={selections}
            dashboard={dashboard}
            loading={selectionRunning}
            error={error}
            onDay={chooseDay}
            onRun={runSelections}
          />
        )}
        {tab === 'programme' && (
          <Program
            dayOffset={dayOffset}
            meetings={meetings}
            selections={selections}
            dashboard={dashboard}
            loading={loading}
            error={error}
            onDay={chooseDay}
            onRefresh={refresh}
            onRace={openRace}
          />
        )}
        {tab === 'results' && (
          <ResultsScreen
            dayOffset={dayOffset}
            meetings={meetings}
            loading={loading}
            error={error}
            onDay={chooseDay}
            onRefresh={refresh}
            onRace={openRace}
          />
        )}
        {tab === 'stats' && <Stats stats={stats} dashboard={dashboard} error={error} />}
        {tab === 'settings' && (
          <Settings
            url={url}
            health={health}
            onChange={setUrl}
            onSave={saveSettings}
          />
        )}
      </View>

      <BottomNav
        tab={tab}
        onSelections={() => switchTab('selections')}
        onProgram={() => switchTab('programme')}
        onResults={() => switchTab('results')}
        onStats={loadStats}
        onSettings={() => switchTab('settings')}
      />
    </SafeAreaView>
  );
}

function SelectionsScreen({
  dayOffset,
  selections,
  dashboard,
  loading,
  error,
  onDay,
  onRun,
}: {
  dayOffset: 0 | 1;
  selections: any;
  dashboard: any;
  loading: boolean;
  error: string;
  onDay: (offset: 0 | 1) => void;
  onRun: () => void;
}) {
  const hasPicks = !!selections?.day && (
    !!selections.day.ready ||
    ['horse', 'placed', 'outsider', 'tocard', 'heart'].some(kind => !!selections.day[kind])
  );
  const dayComplete = !!dashboard?.ready;
  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.selectionHero}>
        <View style={s.heroGlow} />
        <Eyebrow>L’ESSENTIEL HIPPOEDGE</Eyebrow>
        <Text style={s.selectionHeroTitle}>
          {dayOffset === 0 ? 'Sélections du jour' : 'Sélections de demain'}
        </Text>
        <Text style={s.selectionHeroDate}>{longDate(dayOffset)}</Text>
        <Text style={s.selectionHeroText}>
          HippoEdge analyse les courses une par une dans l’ordre chronologique. Les sélections apparaissent dès les premières courses prêtes et évoluent jusqu’à la fin de la journée.
        </Text>
        <DaySwitcher dayOffset={dayOffset} onDay={onDay} />
        <GoldButton
          label={hasPicks ? 'Actualiser les sélections disponibles' : 'Vérifier les premières courses prêtes'}
          icon="▶"
          onPress={onRun}
        />
      </View>
      {!!selections?.day?.data_quality && <DataQualityCard quality={selections.day.data_quality} />}
      {loading && <Loading text="Lecture des sélections pré-calculées…" />}
      {!!error && <ErrorCard title="Analyse interrompue" text={error} />}
      {hasPicks ? (
        <>
          {!dayComplete && (
            <View style={[s.preloadBanner, s.preloadUpdating]}>
              <Text style={[s.preloadTitle, {color: C.goldBright}]}>SÉLECTIONS PROVISOIRES</Text>
              <Text style={s.preloadText}>Elles utilisent uniquement les courses déjà analysées. Elles se mettent à jour automatiquement à mesure que la file chronologique avance.</Text>
            </View>
          )}
          <DayPicks picks={selections.day} />
        </>
      ) : (
        !loading && <EmptyState
          title="Première course en préparation"
          text="HippoEdge traite d’abord la première course chronologique du jour. Sa sélection apparaîtra dès que son analyse complète sera enregistrée."
        />
      )}
      {!!selections?.meetings?.length && (
        <>
          <Section
            eyebrow="RÉUNION PAR RÉUNION"
            title="Nos repères"
            text="Les cinq profils retenus indépendamment dans chaque réunion."
          />
          {selections.meetings.map((meeting: any) => (
            <SelectionMeetingCard key={meeting.meeting_code} meeting={meeting} />
          ))}
        </>
      )}
    </ScrollView>
  );
}

function Program({
  dayOffset,
  meetings,
  selections,
  dashboard,
  loading,
  error,
  onDay,
  onRefresh,
  onRace,
}: {
  dayOffset: 0 | 1;
  meetings: Meeting[];
  selections: any;
  dashboard: any;
  loading: boolean;
  error: string;
  onDay: (offset: 0 | 1) => void;
  onRefresh: () => void;
  onRace: (race: Race) => void;
}) {
  const safeMeetings = Array.isArray(meetings) ? meetings : [];
  const raceCount = safeMeetings.reduce((sum, meeting) => sum + meeting.races.length, 0);
  const [meetingCode, setMeetingCode] = useState<string>('');
  const [raceId, setRaceId] = useState<number | null>(null);
  const activeMeeting = safeMeetings.find(meeting => meeting.code === meetingCode) || safeMeetings[0];
  const activeRace =
    activeMeeting?.races.find(race => race.id === raceId) || activeMeeting?.races[0];

  useEffect(() => {
    if (!safeMeetings.length) {
      setMeetingCode('');
      setRaceId(null);
      return;
    }
    const meeting = safeMeetings.find(item => item.code === meetingCode) || safeMeetings[0];
    if (meeting.code !== meetingCode) setMeetingCode(meeting.code);
    if (!meeting.races.some(race => race.id === raceId)) setRaceId(meeting.races[0]?.id ?? null);
  }, [safeMeetings, meetingCode, raceId]);

  function selectMeeting(meeting: Meeting) {
    setMeetingCode(meeting.code);
    setRaceId(meeting.races[0]?.id ?? null);
  }

  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.programHero}>
        <Eyebrow>PROGRAMME OFFICIEL</Eyebrow>
        <Text style={s.programTitle}>Toutes les courses</Text>
        <Text style={s.programDate}>{longDate(dayOffset)}</Text>
        <DaySwitcher dayOffset={dayOffset} onDay={onDay} />
        <View style={s.programActions}>
          <View style={{flex: 1}}>
            <GoldButton label="Actualiser" icon="↻" onPress={onRefresh} />
          </View>
        </View>
        <View style={s.programStats}>
          <Text style={s.heroStat}>{meetings.length} réunions</Text>
          <View style={s.tinyDot} />
          <Text style={s.heroStat}>{raceCount} courses</Text>
        </View>
        {!!dashboard && (
          <View style={[s.preloadBanner, dashboard.ready ? s.preloadReady : s.preloadUpdating]}>
            <Text style={[s.preloadTitle, dashboard.ready ? {color: C.green} : {color: C.goldBright}]}>
              {dashboard.ready ? '✓ TOUTES LES COURSES DISPONIBLES' : '… ANALYSE COURSE PAR COURSE'}
            </Text>
            <Text style={s.preloadText}>
              {dashboard.activity?.courses_analyzed || 0}/{dashboard.activity?.courses_total || 0} courses déjà disponibles · {dashboard.activity?.horses_analyzed || 0}/{dashboard.activity?.horses_total || 0} chevaux analysés
            </Text>
            {!!dashboard?.next_pending_race && (
              <Text style={s.preloadText}>
                Prochaine dans la file : {dashboard.next_pending_race.meeting_code} · {dashboard.next_pending_race.race_code} · {fmt(dashboard.next_pending_race.scheduled_at)}
              </Text>
            )}
          </View>
        )}
      </View>

      {loading && <Loading text="HippoEdge analyse les données…" />}
      {!!error && <ErrorCard title="Connexion interrompue" text={error} />}
      {!!safeMeetings.length && (
        <>
          <Text style={s.menuLabel}>CHOISIR UNE RÉUNION</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.horizontalMenu}>
            {safeMeetings.map(meeting => (
              <Pressable
                key={meeting.id}
                style={[s.meetingTab, activeMeeting?.code === meeting.code && s.meetingTabActive]}
                onPress={() => selectMeeting(meeting)}>
                <Text style={[s.meetingTabCode, activeMeeting?.code === meeting.code && s.meetingTabCodeActive]}>{meeting.code}</Text>
                <Text numberOfLines={1} style={[s.meetingTabTrack, activeMeeting?.code === meeting.code && s.meetingTabTrackActive]}>{meeting.track}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </>
      )}

      {!!activeMeeting && (
        <View style={s.programMeeting}>
          <View style={s.programMeetingHead}>
            <View style={s.meetingCodeBox}><Text style={s.meetingCode}>{activeMeeting.code}</Text></View>
            <View style={{flex: 1}}>
              <Text style={s.meetingTitle}>{activeMeeting.track}</Text>
              <Text style={s.muted}>{activeMeeting.country ? `${activeMeeting.country} · ` : ''}{activeMeeting.races.length} courses</Text>
            </View>
            <Text style={s.official}>● OFFICIEL</Text>
          </View>
          {(() => {
            const picks = selections?.meetings?.find((x: any) => x.meeting_code === activeMeeting.code);
            return picks ? (
              <View style={s.meetingQuickPicks}>
                <PickLine symbol="◆" label="Meilleur cheval" pick={picks.best} color={C.gold} compact />
                <PickLine symbol="◆" label="Meilleur placé" pick={picks.placed} color={C.green} compact last />
              </View>
            ) : null;
          })()}
          <Text style={s.menuLabelInside}>CHOISIR UNE COURSE</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.courseMenu}>
            {activeMeeting.races.map(race => (
              <Pressable
                key={race.id}
                style={[s.courseTab, activeRace?.id === race.id && s.courseTabActive]}
                onPress={() => setRaceId(race.id)}>
                <Text style={[s.courseTabCode, activeRace?.id === race.id && s.courseTabCodeActive]}>{race.code.replace(`${activeMeeting.code}`, '')}</Text>
                <Text style={[s.courseTabTime, activeRace?.id === race.id && s.courseTabTimeActive]}>{fmt(race.scheduled_at)}</Text>
                {!!race.result && <View style={[s.courseResultDot, race.result.status === 'official' && s.courseResultDotOfficial]} />}
              </Pressable>
            ))}
          </ScrollView>
          {!!activeRace && (
            <CourseMenuCard
              race={activeRace}
              ready={((dashboard?.ready_race_ids || []) as number[]).includes(activeRace.id)}
              queueStatus={(dashboard?.race_queue || []).find((item: any) => item.race_id === activeRace.id)?.status}
              onOpen={() => {
                const ready = ((dashboard?.ready_race_ids || []) as number[]).includes(activeRace.id);
                const queueStatus = (dashboard?.race_queue || []).find((item: any) => item.race_id === activeRace.id)?.status;
                if (ready) {
                  onRace(activeRace);
                } else if (queueStatus === 'missed') {
                  Alert.alert(
                    'Pas de snapshot pré-course',
                    'Cette course avait déjà démarré avant que cette version puisse publier son analyse. HippoEdge ne fabrique jamais un pronostic rétroactivement.',
                  );
                } else {
                  Alert.alert(
                    'Cette course est dans la file',
                    'HippoEdge traite les courses du jour une par une dans l’ordre chronologique. Dès que celle-ci est terminée, son analyse devient immédiatement accessible sans attendre les autres courses.',
                  );
                }
              }}
            />
          )}
        </View>
      )}
      {!loading && !safeMeetings.length && <EmptyState title="Programme indisponible" text="Aucune réunion chargée pour cette date." />}
    </ScrollView>
  );
}

function DayPicks({picks}: {picks: any}) {
  return (
    <View style={s.dayBlock}>
      <Section
        eyebrow="SIGNATURE HIPPOEDGE"
        title="Les choix du jour"
        text="Une synthèse issue uniquement de notre moteur indépendant."
      />
      <View style={s.featured}>
        <View style={s.featuredGlow} />
        <View style={s.featuredRow}>
          <View style={{flex: 1}}>
            <Text style={s.featuredLabel}>CHEVAL DU JOUR</Text>
            <Text style={s.featuredHorse}>
              {picks.horse ? `N°${picks.horse.number}  ${picks.horse.horse_name}` : '—'}
            </Text>
            <Text style={s.featuredPlace}>
              {picks.horse
                ? `${picks.horse.meeting_code} · ${picks.horse.race_code}`
                : 'En attente des analyses'}
            </Text>
          </View>
          <View style={s.featuredScore}>
            <Text style={s.featuredScoreValue}>
              {picks.horse
                ? Math.round(picks.horse.selection_score ?? picks.horse.performance)
                : '—'}
            </Text>
            <Text style={s.featuredScoreLabel}>INDICE</Text>
          </View>
        </View>
        <View style={s.goldLine} />
        <Text style={s.featuredText}>
          {picks.horse?.selection_reason ||
            'Le profil offrant la meilleure lecture globale parmi toutes les réunions de la journée.'}
        </Text>
      </View>
      <View style={s.picksCard}>
        <PickLine symbol="◆" label="Meilleur placé" pick={picks.placed} color={C.green} />
        <PickLine symbol="◇" label="Outsider analytique" pick={picks.outsider} color={C.blue} />
        <PickLine symbol="↗" label="Tocard spéculatif" pick={picks.tocard} color={C.purple} />
        <PickLine symbol="♥" label="Cheval de cœur" pick={picks.heart} color={C.coral} last />
      </View>
      <View style={s.firewallNote}>
        <Text style={s.firewallIcon}>✓</Text>
        <Text style={s.firewallText}>
          Aucune cote, aucun favori et aucun pronostic extérieur ne participent à ces choix.
        </Text>
      </View>
    </View>
  );
}

function SelectionMeetingCard({meeting}: {meeting: any}) {
  return (
    <View style={s.meeting}>
      <View style={s.meetingHead}>
        <View style={s.meetingCodeBox}>
          <Text style={s.meetingCode}>{meeting.meeting_code}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.meetingTitle}>{meeting.track}</Text>
          <Text style={s.muted}>Sélections approfondies de la réunion</Text>
        </View>
        <Text style={s.official}>{meeting.ready ? '● ANALYSÉE' : '○ EN ATTENTE'}</Text>
      </View>
      <View style={s.meetingPicks}>
        <PickLine symbol="◆" label="Meilleur cheval" pick={meeting.best} color={C.gold} />
        <PickLine symbol="◆" label="Meilleur placé" pick={meeting.placed} color={C.green} />
        <PickLine symbol="◇" label="Outsider" pick={meeting.outsider} color={C.blue} />
        <PickLine symbol="↗" label="Tocard" pick={meeting.tocard} color={C.purple} />
        <PickLine symbol="♥" label="Cheval de cœur" pick={meeting.heart} color={C.coral} last />
      </View>
    </View>
  );
}

function CourseMenuCard({race, ready, queueStatus, onOpen}: {race: Race; ready: boolean; queueStatus?: string; onOpen: () => void}) {
  return (
    <View style={s.courseCard}>
      <View style={s.courseCardTop}>
        <View style={s.courseCodeLarge}><Text style={s.courseCodeLargeText}>{race.code.split('C').pop()}</Text></View>
        <View style={{flex: 1}}>
          <Text style={s.courseTime}>{fmt(race.scheduled_at)}</Text>
          <Text style={s.courseName}>{race.name}</Text>
        </View>
        {!!race.result && <ResultStatus status={race.result.status} compact />}
      </View>
      <View style={s.courseFacts}>
        <Chip text={plainLabel(race.discipline)} />
        <Chip text={`${race.distance_m || '?'} m`} />
        <Chip text={`${race.runners.length} partants`} />
        {!!race.class_name && <Chip text={plainLabel(race.class_name)} />}
        {!!race.purse_eur && <Chip text={`${Math.round(race.purse_eur).toLocaleString('fr-FR')} €`} />}
      </View>
      {!!race.result && <Arrival result={race.result} />}
      <GoldButton
        label={ready ? "Ouvrir l’analyse instantanée" : queueStatus === 'missed' ? "Pas d’analyse pré-course" : "Dans la file chronologique…"}
        icon={ready ? "→" : queueStatus === 'missed' ? "×" : "…"}
        onPress={onOpen}
      />
    </View>
  );
}

function ResultsScreen({
  dayOffset,
  meetings,
  loading,
  error,
  onDay,
  onRefresh,
  onRace,
}: {
  dayOffset: 0 | 1;
  meetings: Meeting[];
  loading: boolean;
  error: string;
  onDay: (offset: 0 | 1) => void;
  onRefresh: () => void;
  onRace: (race: Race) => void;
}) {
  const rows = meetings.flatMap(meeting =>
    meeting.races
      // Keep provisional rows visible even when the source has published only
      // the status and is still assembling the order.
      .filter(race => !!race.result)
      .map(race => ({meeting, race})),
  );
  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.pageIntro}>
        <Eyebrow>ARRIVÉES PMU</Eyebrow>
        <Text style={s.pageTitle}>Résultats</Text>
        <Text style={s.pageText}>
          Les arrivées provisoires sont signalées immédiatement puis remplacées par le résultat officiel.
        </Text>
        <DaySwitcher dayOffset={dayOffset} onDay={onDay} />
        <GoldButton label="Actualiser les arrivées" icon="↻" onPress={onRefresh} />
      </View>
      {loading && <Loading text="Vérification des arrivées…" />}
      {!!error && <ErrorCard title="Résultats indisponibles" text={error} />}
      {!loading && !rows.length && (
        <EmptyState
          title="Aucune arrivée pour le moment"
          text={dayOffset === 0 ? 'Les résultats apparaîtront ici dès leur publication.' : 'Les courses de demain ne sont pas encore disputées.'}
        />
      )}
      {rows.map(({meeting, race}) => (
        <View key={race.id} style={s.resultCard}>
          <View style={s.resultCardHead}>
            <View style={s.resultMeetingCode}><Text style={s.resultMeetingCodeText}>{meeting.code}</Text></View>
            <View style={{flex: 1}}>
              <Text style={s.resultTrack}>{meeting.track} · {race.code}</Text>
              <Text numberOfLines={1} style={s.resultRaceName}>{race.name}</Text>
            </View>
            <ResultStatus status={race.result!.status} />
          </View>
          <Arrival result={race.result!} />
          <Pressable style={s.resultAnalysisButton} onPress={() => onRace(race)}>
            <Text style={s.resultAnalysisText}>Voir l’analyse pré-course</Text>
            <Text style={s.resultAnalysisArrow}>›</Text>
          </Pressable>
        </View>
      ))}
      <View style={s.firewallNote}>
        <Text style={s.firewallIcon}>✓</Text>
        <Text style={s.firewallText}>Les arrivées servent à mesurer la méthode. Elles ne réécrivent jamais l’analyse figée avant le départ.</Text>
      </View>
    </ScrollView>
  );
}

function ResultStatus({status, compact = false}: {status: 'provisional' | 'official'; compact?: boolean}) {
  const official = status === 'official';
  return (
    <View style={[s.resultStatus, official ? s.resultStatusOfficial : s.resultStatusProvisional, compact && s.resultStatusCompact]}>
      <View style={[s.resultStatusDot, {backgroundColor: official ? C.green : C.gold}]} />
      <Text style={[s.resultStatusText, {color: official ? C.green : C.goldBright}]}>{official ? 'OFFICIELLE' : 'PROVISOIRE'}</Text>
    </View>
  );
}

function Arrival({result}: {result: NonNullable<Race['result']>}) {
  return (
    <View style={s.arrivalBox}>
      <Text style={s.arrivalLabel}>ARRIVÉE</Text>
      <View style={s.arrivalRow}>
        {result.official_order.slice(0, 8).map((number, index) => (
          <View key={`${number}-${index}`} style={[s.arrivalPlace, index === 0 && s.arrivalWinner]}>
            <Text style={[s.arrivalRank, index === 0 && s.arrivalRankWinner]}>{index + 1}</Text>
            <Text style={[s.arrivalNumber, index === 0 && s.arrivalNumberWinner]}>{number}</Text>
          </View>
        ))}
      </View>
      {!result.official_order.length && (
        <Text style={s.arrivalPending}>Ordre d’arrivée en cours de publication.</Text>
      )}
      {!!result.non_finishers?.length && <Text style={s.nonFinishers}>Non classés : {result.non_finishers.join(' – ')}</Text>}
    </View>
  );
}

function DaySwitcher({dayOffset, onDay}: {dayOffset: 0 | 1; onDay: (offset: 0 | 1) => void}) {
  return (
    <View style={s.segmented}>
      <Segment active={dayOffset === 0} label="Aujourd’hui" onPress={() => onDay(0)} />
      <Segment active={dayOffset === 1} label="Demain" onPress={() => onDay(1)} />
    </View>
  );
}

function EmptyState({title, text}: {title: string; text: string}) {
  return (
    <View style={s.emptyState}>
      <Text style={s.emptyIcon}>◇</Text>
      <Text style={s.emptyTitle}>{title}</Text>
      <Text style={s.emptyText}>{text}</Text>
    </View>
  );
}

function Stats({stats, dashboard, error}: {stats: any; dashboard: any; error: string}) {
  const [windowDays, setWindowDays] = useState<3 | 7 | 14 | 30>(30);
  const activity = dashboard?.activity || {};
  const engagements = (dashboard?.engagements?.items || []).filter(
    (item: any) => Number(item?.next?.days_after ?? 999) <= windowDays,
  );

  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.pageIntro}>
        <Eyebrow>ACTIVITÉ HIPPOEDGE</Eyebrow>
        <Text style={s.pageTitle}>Journal du jour</Text>
        <Text style={s.pageText}>
          Les compteurs viennent de la base persistante. Un redémarrage Render ne remet pas les analyses ou les engagements connus à zéro.
        </Text>
      </View>
      {!!error && <Text style={s.error}>{error}</Text>}

      {!!dashboard && (
        <>
          <View style={[s.preloadBanner, dashboard.ready ? s.preloadReady : s.preloadUpdating]}>
            <Text style={[s.preloadTitle, dashboard.ready ? {color: C.green} : {color: C.goldBright}]}>
              {dashboard.ready ? '✓ FILE DU JOUR TERMINÉE' : '… ANALYSE CHRONOLOGIQUE EN COURS'}
            </Text>
            <Text style={s.preloadText}>
              {activity.courses_analyzed || 0}/{activity.courses_total || 0} courses disponibles · {activity.horses_analyzed || 0}/{activity.horses_total || 0} chevaux analysés
            </Text>
          </View>

          <Section
            eyebrow="ACTIVITÉ DU JOUR"
            title="Ce qu’HippoEdge a réellement traité"
            text="Chevaux et courses uniques de la journée, plus l’avancement du réseau historique."
          />
          <View style={s.statsGrid}>
            <Stat label="Courses analysées" value={`${activity.courses_analyzed || 0}/${activity.courses_total || 0}`} featured />
            <Stat label="Chevaux analysés" value={`${activity.horses_analyzed || 0}/${activity.horses_total || 0}`} />
            <Stat label="Courses encore dans la file" value={activity.courses_updating || 0} />
            <Stat label="Courses parties sans snapshot pré-course" value={activity.courses_missed_without_prerace || 0} />
            <Stat label="Courses historiques uniques recroisées" value={`${activity.historical_unique_courses_linked || 0}/${activity.historical_unique_courses_total || 0}`} />
            <Stat label="Lignes de performances reliées" value={`${activity.historical_rows_linked || 0}/${activity.historical_rows_total || 0}`} />
            <Stat label="Profils vérifiés" value={`${activity.profiles_checked || 0}/${activity.profiles_total || 0}`} />
            <Stat label="Anciennes courses en cache global" value={activity.cached_historical_races_global || 0} />
          </View>

          <Section
            eyebrow="ENGAGEMENTS FUTURS"
            title="Chevaux de la journée déjà revus au programme"
            text={`${dashboard.engagements?.count || 0} cheval${Number(dashboard.engagements?.count || 0) > 1 ? 'aux' : ''} de la journée possède${Number(dashboard.engagements?.count || 0) > 1 ? 'nt' : ''} déjà un engagement futur connu${dashboard.engagements?.programs_known_through ? ` · programmes chargés jusqu’au ${dashboard.engagements.programs_known_through}` : ''}.`}
          />
          <View style={s.filterRow}>
            {[3, 7, 14, 30].map(days => (
              <Pressable
                key={days}
                style={[s.filterChip, windowDays === days && s.filterChipActive]}
                onPress={() => setWindowDays(days as 3 | 7 | 14 | 30)}>
                <Text style={[s.filterChipText, windowDays === days && s.filterChipTextActive]}>≤ {days} j</Text>
              </Pressable>
            ))}
          </View>

          {!engagements.length && (
            <EmptyState
              title="Aucun engagement futur connu"
              text={`Aucun cheval de la journée sélectionnée n’est actuellement retrouvé dans un programme futur à ≤ ${windowDays} jours.`}
            />
          )}
          {engagements.map((item: any, index: number) => (
            <View key={`${item.horse_external_id || item.horse_name}-${item.today?.race_id}-${index}`} style={s.engagementCard}>
              <View style={s.engagementHead}>
                <View style={{flex: 1}}>
                  <Text style={s.engagementHorse}>{item.horse_name}</Text>
                  <Text style={s.engagementToday}>
                    Course sélectionnée · {item.today?.meeting_code} {item.today?.race_code} · {item.today?.track}
                  </Text>
                </View>
                <View style={s.delayBadge}><Text style={s.delayText}>J+{item.next?.days_after || 0}</Text></View>
              </View>
              <View style={s.engagementArrowRow}>
                <Text style={s.engagementArrow}>↓</Text>
                <View style={{flex: 1}}>
                  <Text style={s.engagementNext}>
                    {item.next?.date} · {item.next?.meeting_code} {item.next?.race_code} · {item.next?.track}
                  </Text>
                  <Text style={s.engagementMeta}>
                    {plainLabel(item.next?.discipline)}{item.next?.distance_m ? ` · ${item.next.distance_m} m` : ''} · {item.next?.status === 'non_partant' ? 'non-partant' : 'au programme'}
                  </Text>
                </View>
              </View>
              {Number(item.known_future_count || 0) > 1 && (
                <Text style={s.engagementMore}>+ {Number(item.known_future_count) - 1} autre(s) engagement(s) connu(s)</Text>
              )}
            </View>
          ))}
        </>
      )}

      <Section eyebrow="PERFORMANCE DU MODÈLE" title="Bilan des snapshots verrouillés" />
      {!!stats && (
        <View style={s.statsGrid}>
          <Stat label="Courses évaluées" value={stats.races_evaluees} featured />
          <Stat label="Choix gagnant" value={stats.choix_gagnant_pct != null ? `${stats.choix_gagnant_pct}%` : '—'} />
          <Stat label="Choix placé Top 3" value={stats.choix_place_top3_pct != null ? `${stats.choix_place_top3_pct}%` : '—'} />
          <Stat label="Gagnant dans Top 3" value={stats.gagnant_dans_top3_performance_pct != null ? `${stats.gagnant_dans_top3_performance_pct}%` : '—'} />
        </View>
      )}

      <View style={s.infoCard}>
        <Eyebrow>PROTOCOLE</Eyebrow>
        <Text style={s.infoTitle}>Mesurer sans réécrire</Text>
        <Text style={s.body}>
          Chaque snapshot conserve les scores tels qu’ils existaient avant le départ. Les résultats servent ensuite uniquement à mesurer la précision réelle de la méthode.
        </Text>
      </View>
    </ScrollView>
  );
}


function Settings({
  url,
  health,
  onChange,
  onSave,
}: {
  url: string;
  health: any;
  onChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.pageIntro}>
        <Eyebrow>CONFIGURATION</Eyebrow>
        <Text style={s.pageTitle}>Serveur de données</Text>
        <Text style={s.pageText}>Indique l’adresse locale ou HTTPS du backend HippoEdge.</Text>
      </View>
      <View style={s.settingsCard}>
        <Text style={s.fieldLabel}>ADRESSE DE L’API</Text>
        <TextInput
          style={s.input}
          value={url}
          onChangeText={onChange}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://192.168.1.25:8000"
          placeholderTextColor={C.mutedDark}
        />
        <GoldButton label="Enregistrer et tester" icon="→" onPress={onSave} />
        {!!health && (
          <View style={s.connection}>
            <Text style={s.connectionIcon}>✓</Text>
            <View style={{flex: 1}}>
              <Text style={s.connectionTitle}>Connexion active</Text>
              <Text style={s.connectionText}>
                {health.app} · {health.provider} · indépendance protégée
              </Text>
            </View>
          </View>
        )}
      </View>
      <View style={s.ruleCard}>
        <Text style={s.ruleIcon}>◈</Text>
        <View style={{flex: 1}}>
          <Text style={s.ruleTitle}>Règle verrouillée</Text>
          <Text style={s.ruleText}>
            Le backend retire les cotes, favoris, popularité, pronostics et sélections externes avant
            le scoring. Ils ne peuvent pas influencer le classement.
          </Text>
        </View>
      </View>
    </ScrollView>
  );
}

function BottomNav({
  tab,
  onSelections,
  onProgram,
  onResults,
  onStats,
  onSettings,
}: {
  tab: Tab;
  onSelections: () => void;
  onProgram: () => void;
  onResults: () => void;
  onStats: () => void;
  onSettings: () => void;
}) {
  return (
    <View style={s.navWrap}>
      <View style={s.nav}>
        <NavItem active={tab === 'selections'} icon="◆" label="Sélections" onPress={onSelections} />
        <NavItem active={tab === 'programme'} icon="⌁" label="Courses" onPress={onProgram} />
        <NavItem active={tab === 'results'} icon="✓" label="Arrivées" onPress={onResults} />
        <NavItem active={tab === 'stats'} icon="▥" label="Bilan" onPress={onStats} />
        <NavItem active={tab === 'settings'} icon="◉" label="Réglages" onPress={onSettings} />
      </View>
    </View>
  );
}

function NavItem({
  active,
  icon,
  label,
  onPress,
}: {
  active: boolean;
  icon: string;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable style={s.navItem} onPress={onPress}>
      <View style={[s.navIconBox, active && s.navIconBoxActive]}>
        <Text style={[s.navIcon, active && s.navIconActive]}>{icon}</Text>
      </View>
      <Text style={[s.navLabel, active && s.navLabelActive]}>{label}</Text>
    </Pressable>
  );
}

function RaceView({
  race,
  analysis,
  loading,
  error,
  onBack,
  onRefresh,
  onLock,
}: {
  race: Race;
  analysis: Analysis | null;
  loading: boolean;
  error: string;
  onBack: () => void;
  onRefresh: () => void;
  onLock: () => void;
}) {
  const allScores = analysis?.scores || [];
  const performance = useMemo(
    () => allScores.filter(scoreIsRankable).sort((a, b) => b.performance - a.performance),
    [analysis],
  );
  const placed = useMemo(
    () => [...performance].sort((a, b) => b.placed - a.placed),
    [analysis],
  );
  const detailedScores = useMemo(
    () => [...allScores].sort((a, b) => Number(scoreIsRankable(b)) - Number(scoreIsRankable(a)) || b.performance - a.performance),
    [analysis],
  );
  const rankByNumber = useMemo(
    () => new Map(performance.map((score, index) => [score.number, index + 1])),
    [performance],
  );
  const networkRanked = useMemo(
    () => allScores
      .filter(score => opponentNetwork(score)?.eligible === true)
      .sort((a, b) => Number(opponentNetwork(b)?.score || 0) - Number(opponentNetwork(a)?.score || 0)),
    [analysis],
  );
  const networkRankByNumber = useMemo(
    () => new Map(networkRanked.map((score, index) => [score.number, index + 1])),
    [networkRanked],
  );
  const networkDetailed = useMemo(
    () => allScores
      .filter(score => opponentNetwork(score) != null)
      .sort((a, b) =>
        Number(opponentNetwork(b)?.eligible === true) - Number(opponentNetwork(a)?.eligible === true)
        || Number(opponentNetwork(b)?.score || 0) - Number(opponentNetwork(a)?.score || 0)),
    [analysis],
  );
  const finisherTop3 = Array.isArray(analysis?.summary?.finisher_top3_detail)
    ? (analysis?.summary?.finisher_top3_detail as Array<Record<string, any>>)
    : [];
  const lateMoverTop3 = Array.isArray(analysis?.summary?.late_mover_top3_detail)
    ? (analysis?.summary?.late_mover_top3_detail as Array<Record<string, any>>)
    : [];
  const finisherResistanceTop3 = Array.isArray(analysis?.summary?.finisher_resistance_top3_detail)
    ? (analysis?.summary?.finisher_resistance_top3_detail as Array<Record<string, any>>)
    : [];
  const performanceDetail = Array.isArray(analysis?.summary?.top3_performance_detail)
    ? (analysis?.summary?.top3_performance_detail as Array<Record<string, any>>)
    : [];
  const placedDetail = Array.isArray(analysis?.summary?.top3_placed_detail)
    ? (analysis?.summary?.top3_placed_detail as Array<Record<string, any>>)
    : [];
  const hiddenDetail = Array.isArray(analysis?.summary?.hidden_potential_detail)
    ? (analysis?.summary?.hidden_potential_detail as Array<Record<string, any>>)
    : [];
  const robustnessDetail = Array.isArray(analysis?.summary?.robustness_top3_detail)
    ? (analysis?.summary?.robustness_top3_detail as Array<Record<string, any>>)
    : [];
  const volatilityDetail = Array.isArray(analysis?.summary?.low_volatility_top3_detail)
    ? (analysis?.summary?.low_volatility_top3_detail as Array<Record<string, any>>)
    : [];
  const convergenceDetail = Array.isArray(analysis?.summary?.best_convergence_detail)
    ? (analysis?.summary?.best_convergence_detail as Array<Record<string, any>>)
    : [];
  const overlookDetail = Array.isArray(analysis?.summary?.do_not_overlook_detail)
    ? (analysis?.summary?.do_not_overlook_detail as Array<Record<string, any>>)
    : [];
  const selectionDetail = Array.isArray(analysis?.summary?.selection_8_detail)
    ? (analysis?.summary?.selection_8_detail as Array<Record<string, any>>)
    : [];
  const houseTargetDetail = Array.isArray(analysis?.summary?.house_target?.detail)
    ? (analysis?.summary?.house_target?.detail as Array<Record<string, any>>)
    : [];
  const performanceArgument = (number: number) =>
    String(performanceDetail.find(item => Number(item.number) === number)?.argument || '');
  const placedArgument = (number: number) =>
    String(placedDetail.find(item => Number(item.number) === number)?.argument || '');
  return (
    <SafeAreaView style={s.safe}>
      <StatusBar barStyle="light-content" backgroundColor={C.bg} />
      <View style={s.raceHeader}>
        <Pressable style={s.backButton} onPress={onBack}>
          <Text style={s.backArrow}>‹</Text>
          <Text style={s.backText}>Programme</Text>
        </Pressable>
        <Pill gold>{race.code}</Pill>
      </View>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.raceContent}>
        <View style={s.raceHero}>
          <View style={s.raceHeroLine} />
          <Eyebrow>ANALYSE DE COURSE</Eyebrow>
          <Text style={s.raceBig}>{race.name}</Text>
          <View style={s.chips}>
            <Chip text={fmt(race.scheduled_at)} />
            <Chip text={plainLabel(race.discipline)} />
            <Chip text={`${race.distance_m || '?'} m`} />
            {!!race.going && <Chip text={plainLabel(race.going)} />}
            {!!race.start_type && <Chip text={plainLabel(race.start_type)} />}
          </View>
        </View>
        {!!race.result && (
          <View style={s.raceResultCard}>
            <View style={s.raceResultHead}>
              <View>
                <Eyebrow>RÉSULTAT DE LA COURSE</Eyebrow>
                <Text style={s.raceResultTitle}>Arrivée publiée</Text>
              </View>
              <ResultStatus status={race.result.status} />
            </View>
            <Arrival result={race.result} />
            <Text style={s.raceResultNotice}>L’analyse ci-dessous reste celle produite avant l’arrivée et n’a pas été réécrite.</Text>
          </View>
        )}
        {!!analysis && (
          <View style={s.confirm}>
            <Text style={s.confirmIcon}>✓</Text>
            <View style={{flex: 1}}>
              <Text style={s.confirmTitle}>Indépendance confirmée</Text>
              <Text style={s.confirmText}>{analysis.confirmation}</Text>
            </View>
          </View>
        )}
        {!!analysis?.summary?.data_quality && <AnalysisQuality quality={analysis.summary.data_quality} />}
        {!!analysis && <AnalysisGuide />}
        {!!analysis && (
          analysis.summary?.method_complete ? (
            <View style={s.confirm}>
              <Text style={s.confirmIcon}>✓</Text>
              <View style={{flex: 1}}>
                <Text style={s.confirmTitle}>Méthode complète contrôlée</Text>
                <Text style={s.confirmText}>
                  {(analysis.summary?.completed_blocks || []).length}/{(analysis.summary?.required_blocks || []).length} blocs permanents présents. Un bloc sans preuve reste affiché comme insuffisant au lieu d’être oublié.
                </Text>
              </View>
            </View>
          ) : (
            <ErrorCard title="Analyse incomplète" text={`Blocs manquants : ${(analysis.summary?.missing_blocks || []).join(', ') || 'non renseignés'}`} />
          )
        )}
        {analysis?.summary?.snapshot_phase === 'post_start' && (
          <ErrorCard
            title="Lecture tardive"
            text="Cette analyse a été calculée après l’heure de départ faute de snapshot pré-course disponible. Elle est affichée à titre informatif et ne sera jamais utilisée pour évaluer la méthode."
          />
        )}
        {analysis?.summary?.snapshot_phase === 'post_result' && !race.result && (
          <ErrorCard
            title="Diagnostic après course"
            text="Le résultat est enregistré mais aucun snapshot pré-course n’a été retrouvé pour cette course. Cette lecture ne réécrit pas le passé."
          />
        )}
        <View style={s.actions}>
          <Pressable style={s.secondaryButton} onPress={onRefresh}>
            <Text style={s.secondaryText}>↻  Recalculer</Text>
          </Pressable>
          <View style={{flex: 1}}>
            <GoldButton label={analysis?.locked ? 'Figée  ✓' : 'Figer pré-course'} onPress={onLock} />
          </View>
        </View>
        {loading && <Loading text="Calcul des profils en cours…" />}
        {!!error && <ErrorCard title="Analyse indisponible" text={error} />}
        {!!analysis && (
          <>
            <Section
              eyebrow="LECTURE INTÉGRALE"
              title="Cheval par cheval"
              text="Chaque partant est étudié individuellement à partir de son historique et des conditions objectives disponibles."
            />
            {detailedScores.map(score => (
              <RunnerCard key={score.number} rank={rankByNumber.get(score.number) ?? null} score={score} detailed />
            ))}
            <Section
              eyebrow="LIGNES CROISÉES — BLOC INDÉPENDANT"
              title="Réseau des adversaires"
              text="Chaque ancienne course est reliée aux chevaux rencontrés. Le moteur vérifie ensuite leurs répétitions et les chaînes A→B→C→D, avec une influence réduite à chaque liaison."
            />
            {networkDetailed.length ? networkDetailed.map(score => (
              <OpponentLineCard
                key={`network-${score.number}`}
                rank={networkRankByNumber.get(score.number) ?? null}
                score={score}
              />
            )) : (
              <EmptyState
                title="Croisements en préparation"
                text="Les performances sont visibles, mais la liste exacte des adversaires de chaque ancienne course n’est pas encore reliée."
              />
            )}
            <Explanation text={analysis.summary.block_explanations?.opponent_network} color={C.blue} />
            <Section
              eyebrow="FIN DE COURSE — BLOC INDÉPENDANT"
              title="Top 3 — Finisseurs"
              text="Détection d’un vrai profil de finisseur à partir des positions intermédiaires, places gagnées dans la phase finale et sectionnels factuels. Le n°1 doit aussi être une belle chance dans cette course."
            />
            {finisherTop3.length ? finisherTop3.map((item, index) => (
              <FinisherCard key={`finisher-${item.number}`} rank={index + 1} item={item} />
            )) : (
              <EmptyState
                title="Aucun finisseur publiable"
                text="HippoEdge ne force aucun cheval : il faut un déroulement final objectif exploitable et le premier doit aussi être une belle chance actuelle."
              />
            )}
            <Explanation text={analysis.summary.block_explanations?.finisher} color={C.coral} />
            <Section
              eyebrow="REMONTÉE AVANT LE SPRINT FINAL — BLOC INDÉPENDANT"
              title="Top 3 — Progressifs tardifs"
              text="Détection des chevaux qui gagnent plusieurs places avant la toute dernière phase puis soutiennent leur effort jusqu’au poteau. Ce profil est séparé du finisseur pur."
            />
            {lateMoverTop3.length ? lateMoverTop3.map((item, index) => (
              <LateMoverCard key={`late-mover-${item.number}`} rank={index + 1} item={item} />
            )) : (
              <EmptyState
                title="Aucun progressif tardif publiable"
                text="Il faut une remontée objectivement mesurée puis un effort soutenu ; le premier doit aussi être une belle chance dans la course actuelle."
              />
            )}
            <Explanation text={analysis.summary.block_explanations?.late_mover} color={C.blue} />
            <Section
              eyebrow="CONFRONTATION DES STYLES — BLOC INDÉPENDANT"
              title="Top 3 — Résistance aux finisseurs"
              text="Un cheval n’est classé ici que s’il a déjà fini devant un finisseur présent aujourd’hui lors d’une course où ce rival produisait réellement son finish. Une simple confrontation brute ne suffit pas."
            />
            {finisherResistanceTop3.length ? finisherResistanceTop3.map((item, index) => (
              <FinisherResistanceCard key={`finisher-resistance-${item.number}`} rank={index + 1} item={item} />
            )) : (
              <EmptyState
                title="Aucune résistance démontrée"
                text="Aucun cheval du lot n’a encore une preuve directe assez propre face à un finisseur objectivement identifié."
              />
            )}
            <Explanation text={analysis.summary.block_explanations?.finisher_resistance} color={C.green} />
            <Section
              eyebrow="HIÉRARCHIE PRINCIPALE"
              title="Top 3 — Modèle complet"
              text="Les arguments factuels passent avant les notes : résultats passés, contexte, lignes et risques expliquent chaque choix."
            />
            {performance.length ? performance.slice(0, 3).map((score, index) => (
              <RunnerCard key={`top-${score.number}`} rank={index + 1} score={score} argument={performanceArgument(score.number)} />
            )) : <EmptyState title="Classement en attente" text="Aucun cheval n’a encore assez de performances fiables pour établir ce Top 3." />}
            <Explanation text={analysis.summary.block_explanations?.performance} color={C.gold} />
            <Section
              eyebrow="SÉCURITÉ"
              title="Top 3 — Simple Placé"
              text="Chaque choix est justifié d’abord par sa régularité, ses références et sa capacité à répéter son effort ; la note /100 reste un repère secondaire."
            />
            {placed.length ? placed.slice(0, 3).map((score, index) => (
              <RunnerCard key={`placed-${score.number}`} rank={index + 1} score={score} placed argument={placedArgument(score.number)} />
            )) : <EmptyState title="Classement placé en attente" text="Les données disponibles ne permettent pas encore de recommander un cheval pour une place." />}
            <Explanation text={analysis.summary.block_explanations?.placed} color={C.green} />

            <Section
              eyebrow="VALEUR MASQUÉE"
              title="Top 3 — Potentiel caché"
              text="Anciennes valeurs, progression masquée, aptitude et configuration sont expliquées avec leurs faits. Le score /100 reste secondaire."
            />
            <ArgumentRanking details={hiddenDetail} scores={allScores} />
            <Explanation text={analysis.summary.block_explanations?.hidden_potential} color={C.purple} />

            <Section
              eyebrow="SCÉNARIOS DE COURSE"
              title="Top 3 — Robustesse"
              text="Capacité à rester compétitif malgré rythme, position, trafic, trajectoire ou ouverture tardive."
            />
            <ArgumentRanking details={robustnessDetail} scores={allScores} />
            <Explanation text={analysis.summary.block_explanations?.robustness} color={C.blue} />

            <Section
              eyebrow="CONFIANCE / INCERTITUDE"
              title="Top 3 — Faible volatilité"
              text="Les profils les plus mesurables sont argumentés avant l’indicateur d’incertitude. Une faible volatilité ne remplace jamais la valeur sportive."
            />
            <ArgumentRanking details={volatilityDetail} scores={allScores} placed />
            <Explanation text={analysis.summary.block_explanations?.volatility} color={C.coral} />

            <Section
              eyebrow="DOUBLE VALIDATION"
              title="Top 3 — Convergence"
              text="Chevaux qui ressortent simultanément dans la lecture Performance et la lecture Placé, avec les raisons factuelles de cette convergence."
            />
            <ArgumentRanking details={convergenceDetail} scores={allScores} />
            <Explanation text={analysis.summary.block_explanations?.convergence} color={C.coral} />

            <Section
              eyebrow="PROFILS SECONDAIRES"
              title="À ne pas négliger"
              text="Chevaux hors des premières lignes dont un argument objectif distinct mérite d’être vu par le joueur."
            />
            {overlookDetail.length ? (
              <ArgumentRanking details={overlookDetail} scores={allScores} />
            ) : (
              <EmptyState title="Aucun profil distinct" text="Aucun cheval supplémentaire ne possède actuellement un argument suffisamment différent des principaux choix." />
            )}
            <Explanation text={analysis.summary.block_explanations?.do_not_overlook} color={C.blue} />

            <Section
              eyebrow="SÉLECTION ÉLARGIE"
              title="Jusqu’à 8 chevaux"
              text="Ordre interne élargi avec un argument joueur pour chaque cheval retenu. Toujours sans cote ni verdict extérieur."
            />
            <ArgumentRanking details={selectionDetail} scores={allScores} />
            <Explanation text={analysis.summary.block_explanations?.selection_8} color={C.muted} />

            <Section
              eyebrow="PARAMÈTRES RENFORCÉS"
              title="Lecture croisée de tous les modules"
              text="Lignes A→B→C→D, potentiel caché, robustesse, volatilité et styles de fin de course sont rapprochés sans modifier leurs classements indépendants."
            />
            <Explanation text={analysis.summary.block_explanations?.reinforced_parameters} color={C.gold} />

            <Synthesis analysis={analysis} />
            <Conclusion analysis={analysis} />

            <Section
              eyebrow="BLOC INDÉPENDANT — APRÈS LA CONCLUSION"
              title="Course potentiellement ciblée / engagements"
              text="HippoEdge recherche les répétitions objectives de programme, retour sur hippodrome/distance/catégorie, changement d’équipement et prochains engagements déjà publiés. Aucune intention d’entourage n’est inventée et ce bloc ne change aucun score."
            />
            {houseTargetDetail.length ? houseTargetDetail.map((item, index) => (
              <TargetCard key={`target-${item.number}`} rank={index + 1} item={item} />
            )) : (
              <EmptyState
                title="Aucune course cible démontrée"
                text="Aucun indice objectif suffisamment précis. Le bloc reste volontairement présent au lieu d’être oublié."
              />
            )}
            <Explanation text={analysis.summary.block_explanations?.house_target} color={C.gold} />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function ArgumentRanking({
  details,
  scores,
  placed = false,
}: {
  details: Array<Record<string, any>>;
  scores: Score[];
  placed?: boolean;
}) {
  const byNumber = new Map(scores.map(score => [Number(score.number), score]));
  if (!details.length) {
    return <EmptyState title="Aucune sélection publiable" text="Le bloc reste présent, mais les preuves disponibles ne permettent pas de classer un cheval de façon fiable." />;
  }
  return (
    <>
      {details.map((item, index) => {
        const score = byNumber.get(Number(item.number));
        if (!score) return null;
        return (
          <RunnerCard
            key={`argument-${String(item.number)}-${index}`}
            rank={index + 1}
            score={score}
            placed={placed}
            argument={String(item.argument || '')}
          />
        );
      })}
    </>
  );
}

function TargetCard({rank, item}: {rank: number; item: Record<string, any>}) {
  const future = Array.isArray(item.future_engagements) ? item.future_engagements : [];
  const score = Number(item.score || 0);
  const label = String(item.label || 'SIGNAL INFORMATIF');
  return (
    <View style={[s.runnerCard, rank === 1 && s.runnerRanked]}>
      <View style={s.runnerTop}>
        <View style={[s.rank, rank === 1 && s.rankFirst]}>
          <Text style={[s.rankText, rank === 1 && s.rankTextFirst]}>{rank}</Text>
        </View>
        <View style={s.numberBox}>
          <Text style={s.numberLabel}>N°</Text>
          <Text style={s.numberValue}>{item.number}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.runnerName}>{item.horse_name}</Text>
          <Text style={s.runnerReasons}>{label}</Text>
        </View>
        <View style={s.mainScoreCircle}>
          <Text style={s.mainScore}>{Math.round(score)}</Text>
          <Text style={s.mainScoreUnit}>/100 BLOC</Text>
        </View>
      </View>
      <View style={s.paragraph}>
        <View style={s.paragraphLine} />
        <Text style={s.analysisText}>{String(item.argument || '')}</Text>
      </View>
      {future.length > 0 && (
        <View style={s.networkBridgeList}>
          <Text style={s.networkBridgeTitle}>PROCHAINS ENGAGEMENTS CONNUS</Text>
          {future.slice(0, 3).map((engagement: any, index: number) => (
            <Text key={`target-future-${item.number}-${index}`} style={s.networkBridgeText}>
              • J+{Number(engagement.days_after || 0)} · {String(engagement.date || '—')} · {String(engagement.track || '—')} {String(engagement.race_code || '')}{engagement.distance_m ? ` · ${Number(engagement.distance_m)} m` : ''}.
            </Text>
          ))}
        </View>
      )}
      <Text style={s.networkProof}>Bloc indépendant · n’influence aucun score ni verdict principal</Text>
    </View>
  );
}

function OpponentLineCard({rank, score}: {rank: number | null; score: Score}) {
  const network = opponentNetwork(score) || {};
  const eligible = network.eligible === true;
  const linked = Number(network.linked_races || 0);
  const historyRows = Number(network.history_rows || 0);
  const rivals = Number(network.direct_rivals || 0);
  const confirmations = Number(network.confirmed_lines || 0);
  const higher = Number(network.higher_or_equal_confirmations || 0);
  const chains = Number(network.indirect_chains || 0);
  const thirdChains = Number(network.third_degree_chains || 0);
  const directToday = Number(network.previous_meetings_today || 0);
  const bridges = Number(network.today_opponent_bridges || 0);
  const bridgeExamples = Array.isArray(network.today_bridge_examples) ? network.today_bridge_examples : [];
  const chainExamples = Array.isArray(network.chain_examples) ? network.chain_examples : [];
  return (
    <View style={[s.networkCard, eligible && s.networkCardRanked, !eligible && s.networkCardLimited]}>
      <View style={s.networkTop}>
        <View style={[s.networkRank, rank === 1 && s.networkRankFirst]}>
          <Text style={[s.networkRankText, rank === 1 && s.networkRankTextFirst]}>{rank ?? '—'}</Text>
        </View>
        <View style={s.networkNumber}><Text style={s.networkNumberText}>{score.number}</Text></View>
        <View style={{flex: 1}}>
          <Text style={s.networkName}>{score.horse_name}</Text>
          <Text style={s.networkStatus}>{eligible ? 'CLASSÉ SUR LES LIGNES CROISÉES' : 'RÉSEAU INSUFFISANT — NON CLASSÉ'}</Text>
        </View>
        <View style={[s.networkScore, !eligible && s.networkScoreLimited]}>
          <Text style={[s.networkScoreValue, !eligible && s.networkScoreValueLimited]}>{eligible ? Math.round(Number(network.score || 0)) : '—'}</Text>
          <Text style={s.networkScoreUnit}>{eligible ? '/100' : 'ATTENTE'}</Text>
        </View>
      </View>
      <View style={s.networkFacts}>
        <NetworkFact value={`${linked}/${historyRows}`} label="courses reliées" />
        <NetworkFact value={String(rivals)} label="rivaux identifiés" />
        <NetworkFact value={String(confirmations)} label="confirmations" />
        <NetworkFact value={String(chains)} label="chaînes A→B→C / D" />
        <NetworkFact value={String(thirdChains)} label="chaînes jusqu’à D" />
        <NetworkFact value={String(directToday)} label="adversaires du jour déjà croisés" />
        <NetworkFact value={String(bridges)} label="passerelles vers le lot du jour" />
      </View>
      <View style={s.networkParagraph}>
        <View style={s.networkParagraphLine} />
        <Text style={s.networkText}>
          {network.paragraph || 'Le croisement détaillé des adversaires est encore en préparation.'}
        </Text>
      </View>
      {bridgeExamples.length > 0 && (
        <View style={s.networkBridgeList}>
          <Text style={s.networkBridgeTitle}>CE QU’ONT FAIT ENSUITE LES CHEVAUX BATTUS</Text>
          {bridgeExamples.map((example, index) => (
            <Text key={`${score.number}-bridge-${index}`} style={s.networkBridgeText}>• {example}.</Text>
          ))}
        </View>
      )}
      {chainExamples.length > 0 && (
        <View style={s.networkBridgeList}>
          <Text style={s.networkBridgeTitle}>CHAÎNES VÉRIFIÉES A → B → C → D</Text>
          {chainExamples.map((example, index) => (
            <Text key={`${score.number}-chain-${index}`} style={s.networkBridgeText}>• {example}.</Text>
          ))}
        </View>
      )}
      {eligible && higher > 0 && (
        <Text style={s.networkProof}>✓ {higher} confirmation{higher > 1 ? 's' : ''} dans un lot au moins équivalent</Text>
      )}
    </View>
  );
}

function NetworkFact({value, label}: {value: string; label: string}) {
  return (
    <View style={s.networkFact}>
      <Text style={s.networkFactValue}>{value}</Text>
      <Text style={s.networkFactLabel}>{label}</Text>
    </View>
  );
}

function FinisherCard({rank, item}: {rank: number; item: Record<string, any>}) {
  const confirmed = String(item.status || '') === 'confirmed';
  const beautifulChance = item.beautiful_chance === true;
  const score = Number(item.finisher_score || 0);
  const evidenceRuns = Number(item.evidence_runs || 0);
  return (
    <View style={[s.runnerCard, rank === 1 && s.finisherPrimary]}>
      <View style={s.runnerTop}>
        <View style={[s.rank, rank === 1 && s.rankFirst]}>
          <Text style={[s.rankText, rank === 1 && s.rankTextFirst]}>{rank}</Text>
        </View>
        <View style={s.numberBox}>
          <Text style={s.numberLabel}>N°</Text>
          <Text style={s.numberValue}>{item.number}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.runnerName}>{item.horse_name}</Text>
          <Text style={s.runnerReasons}>
            {confirmed ? 'FINISSEUR CONFIRMÉ' : 'FINISSEUR À CONFIRMER'}
            {beautifulChance ? ' · BELLE CHANCE' : ''}
          </Text>
        </View>
        <View style={[s.mainScoreCircle, rank === 1 && s.finisherScoreCircle]}>
          <Text style={s.mainScore}>{Math.round(score)}</Text>
          <Text style={s.mainScoreUnit}>FIN /100</Text>
        </View>
      </View>
      <View style={s.paragraph}>
        <View style={[s.paragraphLine, {backgroundColor: C.coral}]} />
        <Text style={s.analysisText}>{String(item.argument || 'Signal final objectif détecté.')}</Text>
      </View>
      <View style={s.scoreGrid}>
        <ScoreBadge label="Finisseur" value={score} color={C.coral} />
        <ScoreBadge label="Perf" value={Number(item.performance || 0)} color={C.goldBright} />
        <ScoreBadge label="Placé" value={Number(item.placed || 0)} color={C.green} />
        <ScoreBadge label="Preuves" value={evidenceRuns} color={C.blue} />
      </View>
    </View>
  );
}

function LateMoverCard({rank, item}: {rank: number; item: Record<string, any>}) {
  const confirmed = String(item.status || '') === 'confirmed';
  const beautifulChance = item.beautiful_chance === true;
  const score = Number(item.late_mover_score || 0);
  const evidenceRuns = Number(item.evidence_runs || 0);
  return (
    <View style={[s.runnerCard, rank === 1 && s.lateMoverPrimary]}>
      <View style={s.runnerTop}>
        <View style={[s.rank, rank === 1 && s.rankFirst]}>
          <Text style={[s.rankText, rank === 1 && s.rankTextFirst]}>{rank}</Text>
        </View>
        <View style={s.numberBox}>
          <Text style={s.numberLabel}>N°</Text>
          <Text style={s.numberValue}>{item.number}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.runnerName}>{item.horse_name}</Text>
          <Text style={s.runnerReasons}>
            {confirmed ? 'PROGRESSIF TARDIF CONFIRMÉ' : 'PROGRESSIF TARDIF À CONFIRMER'}
            {beautifulChance ? ' · BELLE CHANCE' : ''}
          </Text>
        </View>
        <View style={[s.mainScoreCircle, rank === 1 && s.lateMoverScoreCircle]}>
          <Text style={s.mainScore}>{Math.round(score)}</Text>
          <Text style={s.mainScoreUnit}>PROG /100</Text>
        </View>
      </View>
      <View style={s.paragraph}>
        <View style={[s.paragraphLine, {backgroundColor: C.blue}]} />
        <Text style={s.analysisText}>{String(item.argument || 'Remontée tardive soutenue objectivement détectée.')}</Text>
      </View>
      <View style={s.scoreGrid}>
        <ScoreBadge label="Progressif" value={score} color={C.blue} />
        <ScoreBadge label="Perf" value={Number(item.performance || 0)} color={C.goldBright} />
        <ScoreBadge label="Placé" value={Number(item.placed || 0)} color={C.green} />
        <ScoreBadge label="Preuves" value={evidenceRuns} color={C.purple} />
      </View>
    </View>
  );
}

function FinisherResistanceCard({rank, item}: {rank: number; item: Record<string, any>}) {
  const confirmed = String(item.status || '') === 'confirmed';
  const score = Number(item.resistance_score || 0);
  const supportRuns = Number(item.support_runs || 0);
  const uniqueFinishers = Number(item.unique_finishers || 0);
  const chanceLabel = String(item.chance_label || 'SIGNAL INDÉPENDANT');
  return (
    <View style={[s.runnerCard, rank === 1 && s.finisherResistancePrimary]}>
      <View style={s.runnerTop}>
        <View style={[s.rank, rank === 1 && s.rankFirst]}>
          <Text style={[s.rankText, rank === 1 && s.rankTextFirst]}>{rank}</Text>
        </View>
        <View style={s.numberBox}>
          <Text style={s.numberLabel}>N°</Text>
          <Text style={s.numberValue}>{item.number}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.runnerName}>{item.horse_name}</Text>
          <Text style={s.runnerReasons}>
            {confirmed ? 'RÉSISTANT AUX FINISSEURS CONFIRMÉ' : 'RÉSISTANCE À CONFIRMER'} · {chanceLabel}
          </Text>
        </View>
        <View style={[s.mainScoreCircle, rank === 1 && s.finisherResistanceScoreCircle]}>
          <Text style={s.mainScore}>{Math.round(score)}</Text>
          <Text style={s.mainScoreUnit}>RÉS /100</Text>
        </View>
      </View>
      <View style={s.paragraph}>
        <View style={[s.paragraphLine, {backgroundColor: C.green}]} />
        <Text style={s.analysisText}>{String(item.argument || 'Résistance directe à un finisseur du lot objectivement détectée.')}</Text>
      </View>
      <View style={s.scoreGrid}>
        <ScoreBadge label="Résistance" value={score} color={C.green} />
        <ScoreBadge label="Finisseurs contenus" value={uniqueFinishers} color={C.coral} />
        <ScoreBadge label="Confrontations" value={supportRuns} color={C.blue} />
        <ScoreBadge label="Placé" value={Number(item.placed || 0)} color={C.goldBright} />
      </View>
    </View>
  );
}

function RunnerCard({
  rank,
  score,
  placed = false,
  detailed = false,
  argument,
}: {
  rank: number | null;
  score: Score;
  placed?: boolean;
  detailed?: boolean;
  argument?: string;
}) {
  const breakdown = score.breakdown || {};
  const rankable = scoreIsRankable(score);
  const evidenceStatus = String(breakdown.evidence_status || (rankable ? 'partial' : 'insufficient'));
  const evidenceLabel = typeof breakdown.evidence_label === 'string' ? breakdown.evidence_label : undefined;
  const sampleSize = Number(breakdown.sample_size || 0);
  const historyRows = Number(breakdown.history_rows || 0);
  const paragraph = String(
    score.breakdown?.analysis_text ||
      'Données objectives encore insuffisantes pour rédiger une analyse complète.',
  );
  const history = Array.isArray(score.breakdown?.history)
    ? (score.breakdown.history as Array<Record<string, any>>)
    : [];
  return (
    <View style={[s.runnerCard, rank != null && rank <= 3 && s.runnerRanked, !rankable && s.runnerCardLimited]}>
      <View style={s.runnerTop}>
        <View style={[s.rank, rank === 1 && s.rankFirst, rank == null && s.rankLimited]}>
          <Text style={[s.rankText, rank === 1 && s.rankTextFirst]}>{rank ?? '—'}</Text>
        </View>
        <View style={s.numberBox}>
          <Text style={s.numberLabel}>N°</Text>
          <Text style={s.numberValue}>{score.number}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.runnerName}>{score.horse_name}</Text>
          <Text numberOfLines={2} style={s.runnerReasons}>
            {(Array.isArray(score.reasons) ? score.reasons.slice(0, 2).join(' · ') : '') || 'Données encore limitées'}
          </Text>
          <EvidenceBadge status={evidenceStatus} label={evidenceLabel} rankable={rankable} />
        </View>
        <View style={[s.mainScoreCircle, !rankable && s.mainScoreCircleLimited]}>
          <Text style={[s.mainScore, !rankable && s.mainScoreLimited]}>{rankable ? Math.round(placed ? score.placed : score.performance) : '—'}</Text>
          <Text style={[s.mainScoreUnit, !rankable && s.mainScoreUnitLimited]}>{rankable ? '/100' : 'NON CLASSÉ'}</Text>
        </View>
      </View>
      {!!argument && !detailed && (
        <View style={s.paragraph}>
          <View style={s.paragraphLine} />
          <Text style={s.analysisText}>{argument}</Text>
        </View>
      )}
      {!!detailed && (
        <View>
          <View style={s.paragraph}>
            <View style={s.paragraphLine} />
            <Text style={s.analysisText}>{paragraph}</Text>
          </View>
          <Text style={s.evidenceMeta}>
            {historyRows > 0
              ? `${historyRows} performance${historyRows > 1 ? 's' : ''} détaillée${historyRows > 1 ? 's' : ''} contrôlée${historyRows > 1 ? 's' : ''}`
              : sampleSize > 0
                ? `${sampleSize} résultat${sampleSize > 1 ? 's' : ''} officiel${sampleSize > 1 ? 's' : ''} disponible${sampleSize > 1 ? 's' : ''}`
                : 'Aucune performance passée vérifiable pour le moment'}
          </Text>
        </View>
      )}
      {!!detailed && history.length > 0 && <HistoryRows rows={history} />}
      {rankable ? (
        <View style={s.scoreGrid}>
          <ScoreBadge label="Perf" value={score.performance} color={C.goldBright} />
          <ScoreBadge label="Placé" value={score.placed} color={C.green} />
          <ScoreBadge label="Caché" value={score.hidden_potential} color={C.purple} />
          <ScoreBadge label="Robuste" value={score.robustness} color={C.blue} />
          <ScoreBadge label="Volatilité" value={score.uncertainty} color={C.coral} />
        </View>
      ) : (
        <View style={s.notRankedNotice}>
          <Text style={s.notRankedTitle}>Pas de classement publié pour ce dossier</Text>
          <Text style={s.notRankedText}>Les informations du jour restent visibles à titre descriptif, mais elles ne suffisent pas à comparer ce cheval aux autres.</Text>
        </View>
      )}
    </View>
  );
}

function HistoryRows({rows}: {rows: Array<Record<string, any>>}) {
  return (
    <View style={s.historyBox}>
      <View style={s.historyHead}>
        <Text style={s.historyTitle}>RÉFÉRENCES OBJECTIVES</Text>
        <Text style={s.historyCount}>{rows.length} ligne{rows.length > 1 ? 's' : ''}</Text>
      </View>
      {rows.slice(0, 8).map((row, index) => {
        const position = Number(row.position);
        const result = row.disqualified
          ? 'Disq.'
          : Number.isFinite(position) && position > 0
            ? `${position}${position === 1 ? 'er' : 'e'}`
            : 'Non classé';
        const context = [
          row.track,
          row.distance_m ? `${row.distance_m} m` : null,
          row.going ? plainLabel(String(row.going)) : null,
          row.chrono_km_seconds ? `${Number(row.chrono_km_seconds).toFixed(1)} s/km` : null,
        ].filter(Boolean).join(' · ');
        const dateText = row.date
          ? new Date(`${String(row.date)}T12:00:00`).toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit', year: 'numeric'})
          : '—';
        return (
          <View key={`${row.date || 'ligne'}-${index}`} style={s.historyRow}>
            <Text style={s.historyDate}>{dateText}</Text>
            <Text style={[s.historyResult, row.disqualified && s.historyDq]}>{result}</Text>
            <Text numberOfLines={1} style={s.historyContext}>{context || 'Contexte non renseigné'}</Text>
          </View>
        );
      })}
      {rows.length > 8 && <Text style={s.historyMore}>+ {rows.length - 8} autres lignes conservées dans l’analyse</Text>}
    </View>
  );
}

function Synthesis({analysis}: {analysis: Analysis}) {
  return (
    <View style={s.synthesis}>
      <Eyebrow>VISION D’ENSEMBLE</Eyebrow>
      <Text style={s.synthesisTitle}>Synthèse exacte</Text>
      <Insight index="01" label="Top 3 performance" value={(analysis.summary.top3_performance || []).join(' – ')} color={C.gold} />
      <Explanation text={analysis.summary.block_explanations?.performance} color={C.gold} />
      <Insight index="02" label="Top 3 placé" value={(analysis.summary.top3_placed || []).join(' – ')} color={C.green} />
      <Explanation text={analysis.summary.block_explanations?.placed} color={C.green} />
      <Insight index="03" label="Potentiel caché" value={(analysis.summary.hidden_potential || []).join(' – ')} color={C.purple} />
      <Explanation text={analysis.summary.block_explanations?.hidden_potential} color={C.purple} />
      <Insight index="04" label="Robustesse scénario" value={(analysis.summary.robustness_top3 || []).join(' – ')} color={C.blue} />
      <Explanation text={analysis.summary.block_explanations?.robustness} color={C.blue} />
      <Insight index="05" label="Faible volatilité" value={(analysis.summary.low_volatility_top3 || []).join(' – ')} color={C.coral} />
      <Explanation text={analysis.summary.block_explanations?.volatility} color={C.coral} />
      <Insight index="06" label="Convergence" value={(analysis.summary.best_convergence || []).join(' – ')} color={C.coral} />
      <Explanation text={analysis.summary.block_explanations?.convergence} color={C.coral} />
      <Insight index="07" label="À ne pas négliger" value={(analysis.summary.do_not_overlook || []).join(' – ') || 'Aucun profil distinct'} color={C.blue} />
      <Explanation text={analysis.summary.block_explanations?.do_not_overlook} color={C.blue} />
      <Insight index="08" label="Réseau des adversaires — indépendant" value={(analysis.summary.opponent_network_top3 || []).join(' – ') || 'Données insuffisantes'} color={C.blue} />
      <Explanation text={analysis.summary.block_explanations?.opponent_network} color={C.blue} />
      <Insight index="09" label="Finisseurs purs — indépendant" value={(analysis.summary.finisher_top3 || []).join(' – ') || 'Aucun finisseur publiable'} color={C.coral} />
      <Explanation text={analysis.summary.block_explanations?.finisher} color={C.coral} />
      <Insight index="10" label="Progressifs tardifs — indépendant" value={(analysis.summary.late_mover_top3 || []).join(' – ') || 'Aucun progressif tardif publiable'} color={C.blue} />
      <Explanation text={analysis.summary.block_explanations?.late_mover} color={C.blue} />
      <Insight index="11" label="Résistance aux finisseurs — indépendant" value={(analysis.summary.finisher_resistance_top3 || []).join(' – ') || 'Aucune résistance démontrée'} color={C.green} />
      <Explanation text={analysis.summary.block_explanations?.finisher_resistance} color={C.green} />
      <Insight index="12" label="Sélection élargie" value={(analysis.summary.selection_8 || []).join(' – ')} color={C.muted} />
      <Explanation text={analysis.summary.block_explanations?.selection_8} color={C.muted} />
      <Insight index="13" label="Paramètres renforcés" value="Voir le bloc argumenté ci-dessus" color={C.gold} />
      <Explanation text={analysis.summary.block_explanations?.reinforced_parameters} color={C.gold} />
    </View>
  );
}

function Insight({
  index,
  label,
  value,
  color,
}: {
  index: string;
  label: string;
  value: string;
  color: string;
}) {
  return (
    <View style={s.insight}>
      <View style={[s.insightNumber, {borderColor: color}]}>
        <Text style={[s.insightNumberText, {color}]}>{index}</Text>
      </View>
      <View style={{flex: 1}}>
        <Text style={s.insightLabel}>{label}</Text>
        <Text style={s.insightValue}>{value || '—'}</Text>
      </View>
    </View>
  );
}

function Conclusion({analysis}: {analysis: Analysis}) {
  const finalDetail = analysis.summary.final_verdict_detail;
  const winnerLabel = analysis.summary.winning_pick_label ||
    (finalDetail?.cheval_a_battre != null ? `n°${finalDetail.cheval_a_battre}` : '—');
  const dangerLabel = analysis.summary.main_danger_label ||
    (finalDetail?.danger_principal != null ? `n°${finalDetail.danger_principal}` : '—');
  const placedLabel = analysis.summary.rational_place_label ||
    (finalDetail?.choix_rationnel_place != null ? `n°${finalDetail.choix_rationnel_place}` : '—');
  const finalText = finalDetail
    ? `À battre ${winnerLabel} · danger ${dangerLabel} · placé ${placedLabel}`
    : (analysis.summary.final_verdict || []).join(' – ') || '—';
  return (
    <View style={s.conclusion}>
      <View style={s.conclusionGlow} />
      <Text style={s.conclusionKicker}>DÉCISION HIPPOEDGE</Text>
      <Text style={s.conclusionTitle}>Conclusion nette</Text>
      <Text style={s.conclusionIntro}>
        La hiérarchie finale, sans ambiguïté et sans influence extérieure.
      </Text>
      <Verdict index="1" label="Cheval à battre" value={winnerLabel} primary />
      <Verdict index="2" label="Danger principal" value={dangerLabel} />
      <Verdict index="3" label="Choix rationnel pour une place" value={placedLabel} />
      <Verdict index="4" label="Verdict final chiffré" value={finalText} />
      <Verdict index="5" label="Compléments" value={(analysis.summary.complements || []).join(' – ') || '—'} />
      <Explanation text={analysis.summary.block_explanations?.conclusion} color={C.gold} light />
    </View>
  );
}

function Verdict({
  index,
  label,
  value,
  primary = false,
}: {
  index: string;
  label: string;
  value: string;
  primary?: boolean;
}) {
  return (
    <View style={[s.verdict, primary && s.verdictPrimary]}>
      <Text style={[s.verdictIndex, primary && s.verdictIndexPrimary]}>{index}</Text>
      <View style={{flex: 1}}>
        <Text style={s.verdictLabel}>{label}</Text>
        <Text style={[s.verdictValue, primary && s.verdictValuePrimary]}>{value}</Text>
      </View>
    </View>
  );
}

function PickLine({
  symbol,
  label,
  pick,
  color,
  compact = false,
  last = false,
}: {
  symbol: string;
  label: string;
  pick: any;
  color: string;
  compact?: boolean;
  last?: boolean;
}) {
  const score = pick
    ? Math.round(
        pick.selection_score ??
          (label.toLowerCase().includes('placé') ? pick.placed : pick.performance),
      )
    : null;
  return (
    <View style={[s.pickLine, compact && s.pickCompact, !last && s.pickBorder]}>
      <View style={[s.pickSymbol, {borderColor: color}]}>
        <Text style={[s.pickSymbolText, {color}]}>{symbol}</Text>
      </View>
      <View style={{flex: 1}}>
        <Text style={s.pickLabel}>{label}</Text>
        <Text numberOfLines={1} style={s.pickHorse}>
          {pick ? `${pick.meeting_code} ${pick.race_code} · n°${pick.number} ${pick.horse_name}` : '—'}
        </Text>
        {!compact && !!pick?.selection_reason && (
          <Text style={s.pickReason}>{pick.selection_reason}</Text>
        )}
      </View>
      {score != null && (
        <View style={s.pickScoreBox}>
          <Text style={[s.pickScore, {color}]}>{score}</Text>
          <Text style={s.pickScoreLabel}>IND.</Text>
        </View>
      )}
    </View>
  );
}

function Explanation({
  text,
  color,
  light = false,
}: {
  text?: string;
  color: string;
  light?: boolean;
}) {
  if (!text) return null;
  return (
    <View style={[s.explanation, light && s.explanationLight]}>
      <View style={[s.explanationLine, {backgroundColor: color}]} />
      <Text style={[s.explanationText, light && s.explanationTextLight]}>{text}</Text>
    </View>
  );
}

function Stat({label, value, featured = false}: {label: string; value: any; featured?: boolean}) {
  return (
    <View style={[s.stat, featured && s.statFeatured]}>
      <Text style={[s.statValue, featured && s.statValueFeatured]}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
      <View style={[s.statLine, featured && s.statLineFeatured]} />
    </View>
  );
}

function Chip({text}: {text: string}) {
  return (
    <View style={s.chip}>
      <Text style={s.chipText}>{text}</Text>
    </View>
  );
}

function Segment({active, label, onPress}: {active: boolean; label: string; onPress: () => void}) {
  return (
    <Pressable style={[s.segment, active && s.segmentActive]} onPress={onPress}>
      <Text style={[s.segmentText, active && s.segmentTextActive]}>{label}</Text>
    </Pressable>
  );
}

function GoldButton({label, icon, onPress}: {label: string; icon?: string; onPress: () => void}) {
  return (
    <Pressable style={({pressed}) => [s.goldButton, pressed && s.pressed]} onPress={onPress}>
      <Text style={s.goldButtonText}>{label}</Text>
      {!!icon && <Text style={s.goldButtonIcon}>{icon}</Text>}
    </Pressable>
  );
}

function Loading({text}: {text: string}) {
  return (
    <View style={s.loading}>
      <ActivityIndicator size="small" color={C.gold} />
      <Text style={s.loadingText}>{text}</Text>
    </View>
  );
}

function ErrorCard({title, text}: {title: string; text: string}) {
  return (
    <View style={s.errorCard}>
      <Text style={s.errorTitle}>{title}</Text>
      <Text style={s.error}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  safe: {flex: 1, backgroundColor: C.bg},
  screen: {flex: 1},
  header: {minHeight: 74, paddingHorizontal: 18, paddingVertical: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  brandRow: {flexDirection: 'row', alignItems: 'center', gap: 11},
  logo: {width: 42, height: 42, borderRadius: 14, backgroundColor: C.gold, alignItems: 'center', justifyContent: 'center'},
  logoText: {color: '#17130C', fontSize: 14, fontWeight: '900', letterSpacing: -0.6},
  logoDot: {position: 'absolute', right: 5, top: 5, width: 4, height: 4, borderRadius: 2, backgroundColor: C.goldBright},
  brand: {fontSize: 20, fontWeight: '900', color: C.ivory, letterSpacing: -0.5},
  subtitle: {color: C.muted, marginTop: 2, fontSize: 10.5},
  livePill: {flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 99, backgroundColor: '#10211B', borderWidth: 1, borderColor: '#254035'},
  liveDot: {width: 6, height: 6, borderRadius: 3, backgroundColor: C.green},
  liveText: {color: C.green, fontWeight: '900', fontSize: 9, letterSpacing: 1.2},
  content: {paddingHorizontal: 16, paddingTop: 14, paddingBottom: 40, gap: 16},
  raceContent: {paddingHorizontal: 16, paddingTop: 8, paddingBottom: 60, gap: 16},
  eyebrow: {color: C.gold, fontSize: 9.5, fontWeight: '900', letterSpacing: 1.7},
  hero: {minHeight: 326, backgroundColor: '#10131A', borderRadius: 28, borderWidth: 1, borderColor: '#2F2A1D', padding: 22, overflow: 'hidden'},
  heroGlow: {position: 'absolute', width: 210, height: 210, borderRadius: 105, backgroundColor: C.goldDeep, opacity: 0.12, right: -75, top: -80},
  heroTitle: {color: C.ivory, fontSize: 37, lineHeight: 42, fontWeight: '900', letterSpacing: -1.5, marginTop: 13},
  heroDate: {color: C.goldBright, fontSize: 17, fontWeight: '700', textTransform: 'capitalize'},
  heroText: {color: C.muted, lineHeight: 20, fontSize: 13, marginTop: 11, maxWidth: '90%'},
  segmented: {flexDirection: 'row', padding: 4, borderRadius: 14, backgroundColor: '#090C11', borderWidth: 1, borderColor: C.lineSoft, marginTop: 18},
  segment: {flex: 1, paddingVertical: 10, borderRadius: 10, alignItems: 'center'},
  segmentActive: {backgroundColor: C.raised, borderWidth: 1, borderColor: '#373222'},
  segmentText: {color: C.mutedDark, fontWeight: '800', fontSize: 12},
  segmentTextActive: {color: C.goldBright},
  goldButton: {minHeight: 48, borderRadius: 14, backgroundColor: C.gold, paddingHorizontal: 17, paddingVertical: 13, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 12},
  goldButtonText: {color: '#17130C', fontWeight: '900', fontSize: 13},
  goldButtonIcon: {color: '#17130C', fontWeight: '900', fontSize: 19},
  pressed: {opacity: 0.78, transform: [{scale: 0.99}]},
  heroFooter: {flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 15},
  heroStat: {color: C.muted, fontSize: 10.5, fontWeight: '700'},
  tinyDot: {width: 3, height: 3, borderRadius: 2, backgroundColor: C.goldDeep},
  loading: {flexDirection: 'row', alignItems: 'center', gap: 11, backgroundColor: C.card, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: C.lineSoft},
  loadingText: {color: C.muted, fontSize: 12, fontWeight: '700'},
  errorCard: {backgroundColor: '#211215', borderRadius: 14, padding: 14, borderWidth: 1, borderColor: '#5A2D32'},
  errorTitle: {color: '#FFC4C4', fontWeight: '900', marginBottom: 4},
  error: {color: C.red, lineHeight: 18, fontSize: 12},
  qualityCard: {backgroundColor: '#10161A', borderRadius: 20, borderWidth: 1, borderColor: '#294338', padding: 15, gap: 9},
  qualityHead: {flexDirection: 'row', alignItems: 'center', gap: 10},
  qualityIcon: {width: 32, height: 32, borderRadius: 16, backgroundColor: '#182E25', borderWidth: 1, borderColor: '#315543', alignItems: 'center', justifyContent: 'center'},
  qualityIconText: {color: C.green, fontSize: 16, fontWeight: '900'},
  qualityKicker: {color: C.green, fontSize: 7.5, fontWeight: '900', letterSpacing: 1.2},
  qualityTitle: {color: C.ivory, fontSize: 13.5, fontWeight: '900', marginTop: 2},
  qualityPercent: {color: C.goldBright, fontSize: 18, fontWeight: '900'},
  qualityTrack: {height: 5, borderRadius: 3, backgroundColor: '#202A2A', overflow: 'hidden'},
  qualityFill: {height: 5, borderRadius: 3, backgroundColor: C.green},
  qualityText: {color: '#B9C8BE', fontSize: 11.5, lineHeight: 17},
  qualityFoot: {color: C.mutedDark, fontSize: 9.5, lineHeight: 14},
  analysisQuality: {backgroundColor: '#11161D', borderRadius: 17, borderWidth: 1, borderColor: C.line, padding: 14, gap: 7},
  analysisQualityHead: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8},
  analysisQualityTitle: {color: C.ivory, fontSize: 12.5, fontWeight: '900'},
  analysisQualityText: {color: C.muted, fontSize: 11, lineHeight: 17},
  analysisQualityFoot: {color: C.mutedDark, fontSize: 9.5, lineHeight: 14},
  guideCard: {backgroundColor: '#0D1118', borderRadius: 17, borderWidth: 1, borderColor: C.lineSoft, padding: 14, gap: 6},
  guideTitle: {color: C.ivory, fontSize: 12.5, fontWeight: '900'},
  guideText: {color: C.muted, fontSize: 10.5, lineHeight: 17},
  guideStrong: {color: C.goldBright, fontWeight: '900'},
  evidenceBadge: {alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: 5, borderRadius: 99, borderWidth: 1, paddingHorizontal: 7, paddingVertical: 4, marginTop: 5},
  evidenceDot: {width: 5, height: 5, borderRadius: 3},
  evidenceReady: {backgroundColor: '#10211B', borderColor: '#2C4B3C'},
  evidenceLoading: {backgroundColor: '#211C10', borderColor: '#584A2A'},
  evidenceLimited: {backgroundColor: '#211719', borderColor: '#5A2D32'},
  evidenceReadyText: {color: C.green},
  evidenceLoadingText: {color: C.goldBright},
  evidenceLimitedText: {color: '#E4A5A0'},
  evidenceBadgeText: {fontSize: 7.5, fontWeight: '900', letterSpacing: 0.3},
  sectionHead: {marginTop: 6, gap: 5},
  sectionTitle: {color: C.ivory, fontSize: 24, fontWeight: '900', letterSpacing: -0.8},
  sectionText: {color: C.muted, fontSize: 12.5, lineHeight: 19, maxWidth: '94%'},
  dayBlock: {gap: 13, marginTop: 5},
  featured: {backgroundColor: '#17150F', borderRadius: 23, padding: 19, borderWidth: 1, borderColor: '#5A4927', overflow: 'hidden'},
  featuredGlow: {position: 'absolute', width: 145, height: 145, borderRadius: 73, backgroundColor: C.gold, opacity: 0.08, right: -45, top: -50},
  featuredRow: {flexDirection: 'row', alignItems: 'center', gap: 12},
  featuredLabel: {color: C.gold, fontSize: 9, fontWeight: '900', letterSpacing: 1.7},
  featuredHorse: {color: C.ivory, fontSize: 20, fontWeight: '900', marginTop: 7},
  featuredPlace: {color: C.muted, fontSize: 12, fontWeight: '700', marginTop: 4},
  featuredScore: {width: 62, height: 62, borderRadius: 31, borderWidth: 1.5, borderColor: C.gold, backgroundColor: '#0D0D0B', alignItems: 'center', justifyContent: 'center'},
  featuredScoreValue: {color: C.goldBright, fontSize: 22, fontWeight: '900'},
  featuredScoreLabel: {color: C.goldDeep, fontSize: 7, fontWeight: '900', letterSpacing: 0.9},
  goldLine: {height: 1, backgroundColor: '#3A321E', marginVertical: 14},
  featuredText: {color: C.muted, fontSize: 11.5, lineHeight: 18},
  picksCard: {backgroundColor: C.card, borderRadius: 20, borderWidth: 1, borderColor: C.lineSoft, paddingHorizontal: 14, paddingVertical: 5},
  firewallNote: {flexDirection: 'row', gap: 10, alignItems: 'center', paddingHorizontal: 5},
  firewallIcon: {width: 24, height: 24, borderRadius: 12, backgroundColor: '#10211B', color: C.green, borderWidth: 1, borderColor: '#2B4C3E', textAlign: 'center', textAlignVertical: 'center', fontWeight: '900', fontSize: 11},
  firewallText: {flex: 1, color: C.mutedDark, lineHeight: 16, fontSize: 10.5},
  meeting: {backgroundColor: C.card, borderRadius: 23, borderWidth: 1, borderColor: C.lineSoft, overflow: 'hidden'},
  meetingHead: {padding: 15, flexDirection: 'row', gap: 11, alignItems: 'center', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  meetingCodeBox: {width: 44, height: 44, borderRadius: 14, backgroundColor: '#1A170F', borderWidth: 1, borderColor: '#514426', alignItems: 'center', justifyContent: 'center'},
  meetingCode: {color: C.goldBright, fontSize: 15, fontWeight: '900'},
  meetingTitle: {color: C.ivory, fontSize: 16, fontWeight: '900'},
  muted: {color: C.muted, fontSize: 11, lineHeight: 17},
  official: {color: C.green, fontSize: 7.5, fontWeight: '900', letterSpacing: 0.7},
  meetingPicks: {paddingHorizontal: 14, paddingVertical: 10, backgroundColor: '#0A0E14', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  meetingPicksLabel: {color: C.mutedDark, fontSize: 8.5, fontWeight: '900', letterSpacing: 1.4, marginBottom: 5},
  pickLine: {minHeight: 53, flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 7},
  pickCompact: {minHeight: 39, paddingVertical: 3},
  pickBorder: {borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  pickSymbol: {width: 32, height: 32, borderRadius: 11, borderWidth: 1, backgroundColor: '#090C11', alignItems: 'center', justifyContent: 'center'},
  pickSymbolText: {fontSize: 12, fontWeight: '900'},
  pickLabel: {color: C.mutedDark, fontSize: 8.5, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 0.4},
  pickHorse: {color: C.text, fontSize: 11.5, fontWeight: '800', marginTop: 2},
  pickReason: {color: C.mutedDark, fontSize: 9.5, lineHeight: 14, marginTop: 5, paddingRight: 4},
  pickScoreBox: {alignItems: 'center', justifyContent: 'center'},
  pickScore: {fontSize: 17, fontWeight: '900'},
  pickScoreLabel: {color: C.mutedDark, fontSize: 6.5, fontWeight: '900', letterSpacing: 0.6},
  raceRow: {minHeight: 74, paddingHorizontal: 14, paddingVertical: 12, flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  pressedRow: {backgroundColor: C.raised},
  timeBox: {width: 54},
  time: {color: C.goldBright, fontSize: 13, fontWeight: '900'},
  smallCode: {color: C.mutedDark, fontSize: 9, fontWeight: '900', marginTop: 3, letterSpacing: 0.8},
  raceTitle: {color: C.text, fontSize: 13.5, fontWeight: '800'},
  raceMeta: {color: C.mutedDark, fontSize: 10.5, marginTop: 4},
  chevronBox: {width: 28, height: 28, borderRadius: 14, borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center'},
  chevron: {color: C.gold, fontSize: 21, lineHeight: 23, marginTop: -2},
  pageIntro: {paddingVertical: 15, paddingHorizontal: 3, borderBottomWidth: 1, borderBottomColor: C.lineSoft, marginBottom: 4},
  pageTitle: {color: C.ivory, fontSize: 31, fontWeight: '900', letterSpacing: -1.1, marginTop: 8},
  pageText: {color: C.muted, lineHeight: 20, fontSize: 13, marginTop: 9},
  statsGrid: {flexDirection: 'row', flexWrap: 'wrap', gap: 10},
  stat: {flexBasis: '47%', flexGrow: 1, minHeight: 130, backgroundColor: C.card, borderRadius: 20, borderWidth: 1, borderColor: C.lineSoft, padding: 16, justifyContent: 'space-between'},
  statFeatured: {backgroundColor: '#18150F', borderColor: '#514426'},
  statValue: {color: C.ivory, fontSize: 29, fontWeight: '900', letterSpacing: -1},
  statValueFeatured: {color: C.goldBright},
  statLabel: {color: C.muted, fontSize: 11.5, lineHeight: 16, fontWeight: '700'},
  statLine: {height: 2, width: 24, backgroundColor: C.line},
  statLineFeatured: {backgroundColor: C.gold},
  infoCard: {backgroundColor: '#11161F', borderRadius: 20, borderWidth: 1, borderColor: C.lineSoft, padding: 18, gap: 7},
  infoTitle: {color: C.ivory, fontSize: 17, fontWeight: '900'},
  body: {color: C.muted, lineHeight: 20, fontSize: 12.5},
  settingsCard: {backgroundColor: C.card, borderRadius: 22, borderWidth: 1, borderColor: C.lineSoft, padding: 17},
  fieldLabel: {color: C.gold, fontSize: 9, fontWeight: '900', letterSpacing: 1.4, marginBottom: 8},
  input: {backgroundColor: '#090C11', borderWidth: 1, borderColor: C.line, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 14, color: C.ivory, fontSize: 13},
  connection: {flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 15, paddingTop: 15, borderTopWidth: 1, borderTopColor: C.lineSoft},
  connectionIcon: {width: 35, height: 35, borderRadius: 18, backgroundColor: '#10211B', borderWidth: 1, borderColor: '#315543', color: C.green, textAlign: 'center', textAlignVertical: 'center', fontWeight: '900'},
  connectionTitle: {color: C.text, fontWeight: '900', fontSize: 12.5},
  connectionText: {color: C.muted, fontSize: 10.5, marginTop: 2},
  ruleCard: {flexDirection: 'row', gap: 12, backgroundColor: '#11161B', borderRadius: 20, borderWidth: 1, borderColor: '#294035', padding: 17},
  ruleIcon: {width: 38, height: 38, borderRadius: 13, backgroundColor: '#10211B', color: C.green, textAlign: 'center', textAlignVertical: 'center', fontSize: 19, fontWeight: '900'},
  ruleTitle: {color: C.text, fontSize: 14, fontWeight: '900'},
  ruleText: {color: C.muted, fontSize: 11.5, lineHeight: 18, marginTop: 5},
  navWrap: {paddingHorizontal: 14, paddingTop: 8, paddingBottom: 8, borderTopWidth: 1, borderTopColor: C.lineSoft, backgroundColor: C.bg},
  nav: {height: 65, flexDirection: 'row', backgroundColor: C.card, borderRadius: 21, borderWidth: 1, borderColor: C.line, paddingHorizontal: 6},
  navItem: {flex: 1, alignItems: 'center', justifyContent: 'center', gap: 3},
  navIconBox: {minWidth: 39, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center'},
  navIconBoxActive: {backgroundColor: '#242015'},
  navIcon: {color: C.mutedDark, fontSize: 17, fontWeight: '900'},
  navIconActive: {color: C.goldBright},
  navLabel: {color: C.mutedDark, fontSize: 8.2, fontWeight: '800'},
  navLabelActive: {color: C.ivory},
  raceHeader: {minHeight: 64, paddingHorizontal: 16, paddingVertical: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  backButton: {flexDirection: 'row', alignItems: 'center', gap: 5, paddingVertical: 5},
  backArrow: {color: C.gold, fontSize: 28, lineHeight: 28},
  backText: {color: C.text, fontWeight: '800', fontSize: 12.5},
  pill: {paddingHorizontal: 11, paddingVertical: 7, borderRadius: 99, backgroundColor: C.raised, borderWidth: 1, borderColor: C.line},
  pillGold: {backgroundColor: '#1E1A11', borderColor: '#554729'},
  pillText: {color: C.muted, fontSize: 10, fontWeight: '900'},
  pillTextGold: {color: C.goldBright},
  raceHero: {backgroundColor: C.card, borderRadius: 23, borderWidth: 1, borderColor: C.lineSoft, padding: 19, overflow: 'hidden'},
  raceHeroLine: {position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, backgroundColor: C.gold},
  raceBig: {fontSize: 28, lineHeight: 33, fontWeight: '900', color: C.ivory, letterSpacing: -1, marginTop: 8},
  chips: {flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 14},
  chip: {backgroundColor: '#090C11', borderRadius: 99, borderWidth: 1, borderColor: C.line, paddingHorizontal: 9, paddingVertical: 6},
  chipText: {color: C.muted, fontSize: 9.5, fontWeight: '800'},
  confirm: {flexDirection: 'row', gap: 11, alignItems: 'flex-start', backgroundColor: '#10211B', borderWidth: 1, borderColor: '#294A3B', borderRadius: 18, padding: 15},
  confirmIcon: {width: 33, height: 33, borderRadius: 17, backgroundColor: '#182E25', color: C.green, textAlign: 'center', textAlignVertical: 'center', fontWeight: '900'},
  confirmTitle: {color: '#CDE8D9', fontWeight: '900', fontSize: 13},
  confirmText: {color: '#84A897', fontSize: 10.5, lineHeight: 16, marginTop: 4},
  actions: {flexDirection: 'row', gap: 9},
  secondaryButton: {flex: 1, minHeight: 48, borderWidth: 1, borderColor: C.line, backgroundColor: C.card, paddingVertical: 14, paddingHorizontal: 12, borderRadius: 14, alignItems: 'center', justifyContent: 'center'},
  secondaryText: {color: C.text, fontWeight: '900', fontSize: 12},
  networkCard: {backgroundColor: '#0C1219', borderRadius: 21, borderWidth: 1, borderColor: '#203244', padding: 15, gap: 13},
  networkCardRanked: {borderColor: '#35566F'},
  networkCardLimited: {backgroundColor: '#0B0F15', borderColor: '#252D38'},
  networkTop: {flexDirection: 'row', alignItems: 'center', gap: 9},
  networkRank: {width: 29, height: 29, borderRadius: 15, backgroundColor: '#121D28', borderWidth: 1, borderColor: '#35566F', alignItems: 'center', justifyContent: 'center'},
  networkRankFirst: {backgroundColor: C.blue, borderColor: C.blue},
  networkRankText: {color: C.blue, fontSize: 11, fontWeight: '900'},
  networkRankTextFirst: {color: '#091017'},
  networkNumber: {width: 38, height: 44, borderRadius: 11, backgroundColor: '#080C11', alignItems: 'center', justifyContent: 'center'},
  networkNumberText: {color: C.ivory, fontSize: 17, fontWeight: '900'},
  networkName: {color: C.ivory, fontSize: 14.5, fontWeight: '900'},
  networkStatus: {color: C.mutedDark, fontSize: 7.5, fontWeight: '900', letterSpacing: 0.6, marginTop: 4},
  networkScore: {width: 53, height: 53, borderRadius: 27, borderWidth: 1.5, borderColor: '#426C89', alignItems: 'center', justifyContent: 'center', backgroundColor: '#091017'},
  networkScoreLimited: {borderColor: '#343B46'},
  networkScoreValue: {color: '#8BC2E5', fontSize: 19, lineHeight: 20, fontWeight: '900'},
  networkScoreValueLimited: {color: C.mutedDark},
  networkScoreUnit: {color: C.mutedDark, fontSize: 6.2, fontWeight: '900'},
  networkFacts: {flexDirection: 'row', flexWrap: 'wrap', gap: 6},
  networkFact: {flexGrow: 1, flexBasis: '22%', minWidth: 68, minHeight: 50, backgroundColor: '#080C11', borderRadius: 11, borderWidth: 1, borderColor: '#19232D', padding: 7, alignItems: 'center', justifyContent: 'center'},
  networkFactValue: {color: '#8BC2E5', fontSize: 13, fontWeight: '900'},
  networkFactLabel: {color: C.mutedDark, fontSize: 6.8, fontWeight: '800', textAlign: 'center', marginTop: 3},
  networkParagraph: {flexDirection: 'row', gap: 10},
  networkParagraphLine: {width: 2, borderRadius: 1, backgroundColor: '#426C89'},
  networkText: {flex: 1, color: '#AEB7C0', fontSize: 11.5, lineHeight: 18},
  networkBridgeList: {backgroundColor: '#0A1822', borderRadius: 13, borderWidth: 1, borderColor: '#203D52', padding: 11, gap: 7},
  networkBridgeTitle: {color: '#78A9C8', fontSize: 8.5, fontWeight: '900', letterSpacing: 1.1},
  networkBridgeText: {color: '#C3CED9', fontSize: 10.5, lineHeight: 16},
  networkProof: {color: C.green, fontSize: 9.5, fontWeight: '800'},
  runnerCard: {backgroundColor: C.card, borderRadius: 21, borderWidth: 1, borderColor: C.lineSoft, padding: 15, gap: 13},
  runnerRanked: {borderColor: '#2F2E29'},
  finisherPrimary: {borderColor: '#7A493E', backgroundColor: '#15100F'},
  finisherScoreCircle: {borderColor: C.coral},
  lateMoverPrimary: {borderColor: '#315D75', backgroundColor: '#0C141A'},
  lateMoverScoreCircle: {borderColor: C.blue},
  finisherResistancePrimary: {borderColor: '#315D4A', backgroundColor: '#0C1511'},
  finisherResistanceScoreCircle: {borderColor: C.green},
  runnerCardLimited: {backgroundColor: '#0C1016', borderColor: '#242934'},
  runnerTop: {flexDirection: 'row', alignItems: 'center', gap: 9},
  rank: {width: 29, height: 29, borderRadius: 15, backgroundColor: C.raised, borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center'},
  rankLimited: {backgroundColor: '#11151B', borderColor: '#343A45'},
  rankFirst: {backgroundColor: C.gold, borderColor: C.gold},
  rankText: {color: C.muted, fontWeight: '900', fontSize: 11},
  rankTextFirst: {color: '#17130C'},
  numberBox: {width: 38, height: 44, borderRadius: 11, backgroundColor: '#090C11', alignItems: 'center', justifyContent: 'center'},
  numberLabel: {color: C.mutedDark, fontSize: 7, fontWeight: '900'},
  numberValue: {color: C.ivory, fontSize: 17, fontWeight: '900', marginTop: -1},
  runnerName: {color: C.ivory, fontSize: 15, fontWeight: '900'},
  runnerReasons: {color: C.mutedDark, fontSize: 9.5, lineHeight: 14, marginTop: 3},
  mainScoreCircle: {width: 53, height: 53, borderRadius: 27, borderWidth: 1.5, borderColor: C.goldDeep, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0A0C0F'},
  mainScoreCircleLimited: {borderColor: '#353B46'},
  mainScore: {color: C.goldBright, fontSize: 19, fontWeight: '900', lineHeight: 20},
  mainScoreLimited: {color: C.mutedDark},
  mainScoreUnit: {color: C.goldDeep, fontSize: 6.5, fontWeight: '900'},
  mainScoreUnitLimited: {color: C.mutedDark, fontSize: 6},
  paragraph: {flexDirection: 'row', gap: 11, paddingVertical: 2},
  paragraphLine: {width: 2, borderRadius: 1, backgroundColor: C.goldDeep},
  analysisText: {flex: 1, color: '#B2B5BB', lineHeight: 20, fontSize: 12.5},
  evidenceMeta: {color: C.mutedDark, fontSize: 9.5, lineHeight: 14, marginLeft: 13, marginTop: 6},
  notRankedNotice: {backgroundColor: '#11151C', borderRadius: 13, borderWidth: 1, borderColor: '#2B313C', padding: 11, gap: 4},
  notRankedTitle: {color: '#D8D4C9', fontSize: 10.5, fontWeight: '900'},
  notRankedText: {color: C.muted, fontSize: 10.5, lineHeight: 16},
  historyBox: {marginTop: 10, borderRadius: 14, backgroundColor: '#0A0E14', borderWidth: 1, borderColor: C.lineSoft, padding: 11},
  historyHead: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 7},
  historyTitle: {color: C.muted, fontSize: 8, fontWeight: '900', letterSpacing: 1.2},
  historyCount: {color: C.mutedDark, fontSize: 9},
  historyRow: {flexDirection: 'row', alignItems: 'center', gap: 7, paddingVertical: 5, borderTopWidth: 1, borderTopColor: '#151A22'},
  historyDate: {width: 70, color: C.mutedDark, fontSize: 9},
  historyResult: {width: 28, color: C.ivory, fontSize: 10, fontWeight: '900'},
  historyDq: {color: C.coral},
  historyContext: {flex: 1, color: C.muted, fontSize: 9.5},
  historyMore: {color: C.gold, fontSize: 9, marginTop: 7},
  scoreGrid: {flexDirection: 'row', flexWrap: 'wrap', gap: 6},
  scoreBadge: {flexGrow: 1, flexBasis: '18%', minWidth: 57, minHeight: 55, backgroundColor: '#090C11', borderRadius: 12, borderWidth: 1, borderColor: C.lineSoft, paddingVertical: 7, paddingHorizontal: 5, alignItems: 'center', justifyContent: 'center'},
  scoreDot: {width: 4, height: 4, borderRadius: 2, marginBottom: 4},
  scoreLabel: {color: C.mutedDark, fontSize: 7.5, fontWeight: '800'},
  scoreValue: {fontSize: 14, fontWeight: '900', marginTop: 2},
  explanation: {flexDirection: 'row', gap: 10, backgroundColor: '#090C11', borderRadius: 13, padding: 12, marginTop: 2},
  explanationLight: {backgroundColor: 'rgba(7,9,14,0.52)', marginTop: 9},
  explanationLine: {width: 2, borderRadius: 1},
  explanationText: {flex: 1, color: C.muted, fontSize: 11.5, lineHeight: 18},
  explanationTextLight: {color: '#BDB6A5'},
  synthesis: {backgroundColor: '#11161F', borderRadius: 23, borderWidth: 1, borderColor: C.line, padding: 17, gap: 9, marginTop: 5},
  synthesisTitle: {color: C.ivory, fontSize: 22, fontWeight: '900', marginBottom: 3},
  insight: {flexDirection: 'row', alignItems: 'center', gap: 11, paddingVertical: 7, borderTopWidth: 1, borderTopColor: C.lineSoft},
  insightNumber: {width: 34, height: 34, borderRadius: 12, borderWidth: 1, alignItems: 'center', justifyContent: 'center'},
  insightNumberText: {fontSize: 9, fontWeight: '900'},
  insightLabel: {color: C.muted, fontSize: 9.5, fontWeight: '800', textTransform: 'uppercase'},
  insightValue: {color: C.text, fontSize: 13.5, fontWeight: '900', marginTop: 3},
  conclusion: {backgroundColor: '#17140D', borderRadius: 25, borderWidth: 1, borderColor: '#66542C', padding: 19, gap: 8, overflow: 'hidden'},
  conclusionGlow: {position: 'absolute', width: 170, height: 170, borderRadius: 85, backgroundColor: C.gold, opacity: 0.07, top: -70, right: -55},
  conclusionKicker: {color: C.gold, fontSize: 9, fontWeight: '900', letterSpacing: 1.6},
  conclusionTitle: {color: C.ivory, fontSize: 25, fontWeight: '900', letterSpacing: -0.7},
  conclusionIntro: {color: '#948B77', fontSize: 11.5, lineHeight: 17, marginBottom: 5},
  verdict: {flexDirection: 'row', alignItems: 'center', gap: 11, backgroundColor: 'rgba(7,9,14,0.42)', borderRadius: 13, borderWidth: 1, borderColor: '#2C291E', padding: 11},
  verdictPrimary: {backgroundColor: '#211C10', borderColor: '#66542C'},
  verdictIndex: {color: C.goldDeep, fontSize: 11, fontWeight: '900'},
  verdictIndexPrimary: {color: C.goldBright},
  verdictLabel: {color: '#968E7C', fontSize: 9, fontWeight: '800', textTransform: 'uppercase'},
  verdictValue: {color: C.text, fontSize: 13, fontWeight: '900', marginTop: 2},
  verdictValuePrimary: {color: C.goldBright, fontSize: 15},
  houseCard: {backgroundColor: '#13110D', borderRadius: 21, borderWidth: 1, borderColor: '#3E3525', padding: 17, gap: 12},
  houseHead: {flexDirection: 'row', alignItems: 'center', gap: 11},
  houseMark: {width: 38, height: 38, borderRadius: 13, backgroundColor: '#211B10', color: C.gold, textAlign: 'center', textAlignVertical: 'center', fontSize: 17, fontWeight: '900'},
  houseKicker: {color: C.goldDeep, fontSize: 8, fontWeight: '900', letterSpacing: 1.4},
  houseTitle: {color: C.ivory, fontSize: 15, fontWeight: '900', marginTop: 3},
  houseText: {color: '#999081', fontSize: 11.5, lineHeight: 18},
  selectionHero: {backgroundColor: '#10131A', borderRadius: 28, borderWidth: 1, borderColor: '#3C3320', padding: 22, overflow: 'hidden'},
  selectionHeroTitle: {color: C.ivory, fontSize: 31, lineHeight: 35, fontWeight: '900', letterSpacing: -1.1, marginTop: 11},
  selectionHeroDate: {color: C.goldBright, fontSize: 15, fontWeight: '700', textTransform: 'capitalize', marginTop: 2},
  selectionHeroText: {color: C.muted, fontSize: 12.5, lineHeight: 19, marginTop: 11},
  programHero: {backgroundColor: C.card, borderRadius: 23, borderWidth: 1, borderColor: C.lineSoft, padding: 18},
  programTitle: {color: C.ivory, fontSize: 27, fontWeight: '900', letterSpacing: -0.9, marginTop: 8},
  programDate: {color: C.goldBright, fontSize: 14, fontWeight: '700', textTransform: 'capitalize', marginTop: 2},
  programActions: {flexDirection: 'row'},
  programStats: {flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 13},
  menuLabel: {color: C.mutedDark, fontSize: 8.5, fontWeight: '900', letterSpacing: 1.5, marginTop: 2},
  horizontalMenu: {gap: 8, paddingRight: 16},
  meetingTab: {width: 128, minHeight: 58, borderRadius: 16, borderWidth: 1, borderColor: C.line, backgroundColor: C.card, paddingHorizontal: 12, paddingVertical: 10},
  meetingTabActive: {backgroundColor: '#1C180F', borderColor: C.goldDeep},
  meetingTabCode: {color: C.mutedDark, fontSize: 10, fontWeight: '900'},
  meetingTabCodeActive: {color: C.goldBright},
  meetingTabTrack: {color: C.muted, fontSize: 11, fontWeight: '800', marginTop: 4},
  meetingTabTrackActive: {color: C.ivory},
  programMeeting: {backgroundColor: C.card, borderRadius: 23, borderWidth: 1, borderColor: C.lineSoft, overflow: 'hidden'},
  programMeetingHead: {padding: 15, flexDirection: 'row', gap: 11, alignItems: 'center', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  meetingQuickPicks: {paddingHorizontal: 14, paddingVertical: 6, backgroundColor: '#0A0E14', borderBottomWidth: 1, borderBottomColor: C.lineSoft},
  menuLabelInside: {color: C.mutedDark, fontSize: 8.5, fontWeight: '900', letterSpacing: 1.4, paddingHorizontal: 15, paddingTop: 14},
  courseMenu: {gap: 7, paddingHorizontal: 14, paddingVertical: 12},
  courseTab: {minWidth: 72, height: 43, borderRadius: 13, borderWidth: 1, borderColor: C.line, backgroundColor: '#090C11', paddingHorizontal: 10, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center'},
  courseTabActive: {backgroundColor: C.gold, borderColor: C.gold},
  courseTabCode: {color: C.gold, fontSize: 11, fontWeight: '900'},
  courseTabCodeActive: {color: '#17130C'},
  courseTabTime: {color: C.muted, fontSize: 9.5, fontWeight: '800'},
  courseTabTimeActive: {color: '#3A2F19'},
  courseResultDot: {position: 'absolute', width: 6, height: 6, borderRadius: 3, right: 5, top: 5, backgroundColor: C.gold},
  courseResultDotOfficial: {backgroundColor: C.green},
  courseCard: {marginHorizontal: 14, marginBottom: 14, backgroundColor: '#11161F', borderRadius: 19, borderWidth: 1, borderColor: C.line, padding: 15},
  courseCardTop: {flexDirection: 'row', alignItems: 'center', gap: 11},
  courseCodeLarge: {width: 45, height: 48, borderRadius: 14, backgroundColor: '#1D190F', borderWidth: 1, borderColor: '#594928', alignItems: 'center', justifyContent: 'center'},
  courseCodeLargeText: {color: C.goldBright, fontSize: 15, fontWeight: '900'},
  courseTime: {color: C.gold, fontSize: 10, fontWeight: '900'},
  courseName: {color: C.ivory, fontSize: 15, fontWeight: '900', marginTop: 3},
  courseFacts: {flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 13},
  resultStatus: {flexDirection: 'row', alignItems: 'center', gap: 5, borderRadius: 99, borderWidth: 1, paddingHorizontal: 9, paddingVertical: 6},
  resultStatusOfficial: {backgroundColor: '#10211B', borderColor: '#2C4B3C'},
  resultStatusProvisional: {backgroundColor: '#211C10', borderColor: '#584A2A'},
  resultStatusCompact: {paddingHorizontal: 7, paddingVertical: 5},
  resultStatusDot: {width: 5, height: 5, borderRadius: 3},
  resultStatusText: {fontSize: 7.5, fontWeight: '900', letterSpacing: 0.7},
  arrivalBox: {backgroundColor: '#090C11', borderRadius: 15, borderWidth: 1, borderColor: C.lineSoft, padding: 12, marginTop: 13},
  arrivalLabel: {color: C.mutedDark, fontSize: 8, fontWeight: '900', letterSpacing: 1.3, marginBottom: 9},
  arrivalRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 7},
  arrivalPending: {color: C.goldBright, fontSize: 11, lineHeight: 16},
  arrivalPlace: {minWidth: 37, height: 43, borderRadius: 11, backgroundColor: C.raised, borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center'},
  arrivalWinner: {backgroundColor: C.gold, borderColor: C.gold},
  arrivalRank: {color: C.mutedDark, fontSize: 7, fontWeight: '900'},
  arrivalRankWinner: {color: '#5C4924'},
  arrivalNumber: {color: C.ivory, fontSize: 15, fontWeight: '900'},
  arrivalNumberWinner: {color: '#17130C'},
  nonFinishers: {color: C.coral, fontSize: 9.5, fontWeight: '700', marginTop: 9},
  emptyState: {backgroundColor: C.card, borderRadius: 21, borderWidth: 1, borderColor: C.lineSoft, padding: 24, alignItems: 'center'},
  emptyIcon: {color: C.gold, fontSize: 28},
  emptyTitle: {color: C.ivory, fontSize: 16, fontWeight: '900', marginTop: 7},
  emptyText: {color: C.muted, fontSize: 11.5, lineHeight: 18, textAlign: 'center', marginTop: 6},
  resultCard: {backgroundColor: C.card, borderRadius: 21, borderWidth: 1, borderColor: C.lineSoft, padding: 15},
  resultCardHead: {flexDirection: 'row', alignItems: 'center', gap: 10},
  resultMeetingCode: {width: 39, height: 39, borderRadius: 12, backgroundColor: '#1C180F', borderWidth: 1, borderColor: '#554729', alignItems: 'center', justifyContent: 'center'},
  resultMeetingCodeText: {color: C.goldBright, fontSize: 11, fontWeight: '900'},
  resultTrack: {color: C.ivory, fontSize: 12.5, fontWeight: '900'},
  resultRaceName: {color: C.muted, fontSize: 10.5, marginTop: 3},
  resultAnalysisButton: {minHeight: 42, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: C.lineSoft, marginTop: 12, paddingTop: 12},
  resultAnalysisText: {color: C.text, fontSize: 11.5, fontWeight: '800'},
  resultAnalysisArrow: {color: C.gold, fontSize: 22},
  raceResultCard: {backgroundColor: '#11150F', borderRadius: 21, borderWidth: 1, borderColor: '#4B422A', padding: 15},
  raceResultHead: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10},
  raceResultTitle: {color: C.ivory, fontSize: 17, fontWeight: '900', marginTop: 4},
  raceResultNotice: {color: C.mutedDark, fontSize: 9.5, lineHeight: 15, marginTop: 10},
  preloadBanner: {marginTop: 13, borderRadius: 15, borderWidth: 1, paddingHorizontal: 13, paddingVertical: 11, gap: 4},
  preloadReady: {backgroundColor: '#0E1A15', borderColor: '#2D4D3E'},
  preloadUpdating: {backgroundColor: '#1D190F', borderColor: '#584A2A'},
  preloadTitle: {fontSize: 9, fontWeight: '900', letterSpacing: 1.1},
  preloadText: {color: C.muted, fontSize: 10.5, lineHeight: 15},
  filterRow: {flexDirection: 'row', flexWrap: 'wrap', gap: 8},
  filterChip: {borderRadius: 99, borderWidth: 1, borderColor: C.line, backgroundColor: '#0A0D12', paddingHorizontal: 12, paddingVertical: 8},
  filterChipActive: {backgroundColor: '#1D190F', borderColor: C.goldDeep},
  filterChipText: {color: C.muted, fontSize: 10, fontWeight: '800'},
  filterChipTextActive: {color: C.goldBright},
  engagementCard: {backgroundColor: C.card, borderRadius: 18, borderWidth: 1, borderColor: C.lineSoft, padding: 14, gap: 10},
  engagementHead: {flexDirection: 'row', alignItems: 'center', gap: 10},
  engagementHorse: {color: C.ivory, fontSize: 14, fontWeight: '900'},
  engagementToday: {color: C.mutedDark, fontSize: 9.5, marginTop: 3},
  delayBadge: {minWidth: 42, height: 32, borderRadius: 12, backgroundColor: '#1B170E', borderWidth: 1, borderColor: '#574827', alignItems: 'center', justifyContent: 'center'},
  delayText: {color: C.goldBright, fontSize: 10, fontWeight: '900'},
  engagementArrowRow: {flexDirection: 'row', gap: 10, alignItems: 'flex-start'},
  engagementArrow: {color: C.gold, fontSize: 18, lineHeight: 20},
  engagementNext: {color: C.text, fontSize: 11.5, fontWeight: '800', lineHeight: 16},
  engagementMeta: {color: C.muted, fontSize: 10, lineHeight: 15, marginTop: 3},
  engagementMore: {color: C.goldDeep, fontSize: 9.5, fontWeight: '800'},
});
