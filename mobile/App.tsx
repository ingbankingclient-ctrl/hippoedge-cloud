import React, {useEffect, useMemo, useState} from 'react';
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

export default function App() {
  const [tab, setTab] = useState<Tab>('selections');
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selected, setSelected] = useState<Race | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState<any>(null);
  const [url, setUrl] = useState('');
  const [health, setHealth] = useState<any>(null);
  const [dayOffset, setDayOffset] = useState<0 | 1>(0);
  const [selections, setSelections] = useState<any>(null);

  useEffect(() => {
    getBaseUrl().then(setUrl);
    loadProgram();
  }, []);

  async function loadProgram(offset: 0 | 1 = dayOffset) {
    setLoading(true);
    setError('');
    const day = localISO(offset);
    const failures: string[] = [];
    const programTask = Api.program(day)
      .then(program => setMeetings(normalizeMeetings(program)))
      .catch((e: any) => {
        setMeetings([]);
        failures.push(`Programme : ${e?.message || String(e)}`);
      });
    const selectionsTask = Api.selections(day)
      .then(picks => setSelections(picks))
      .catch((e: any) => {
        setSelections(null);
        failures.push(`Sélections : ${e?.message || String(e)}`);
      });
    await Promise.all([programTask, selectionsTask]);
    if (failures.length) setError(failures.join(' · '));
    setLoading(false);
  }

  async function chooseDay(offset: 0 | 1) {
    setDayOffset(offset);
    await loadProgram(offset);
  }

  async function refresh() {
    setLoading(true);
    setError('');
    let refreshError = '';
    try {
      await Api.refresh(localISO(dayOffset));
    } catch (e: any) {
      refreshError = e?.message || String(e);
    }
    await loadProgram(dayOffset);
    if (refreshError) setError(`Actualisation : ${refreshError}`);
  }

  async function openRace(race: Race) {
    setSelected(race);
    setAnalysis(null);
    setLoading(true);
    setError('');
    try {
      const loaded = await Api.analysis(race.id);
      setAnalysis(loaded);
      if (loaded.result && !race.result) {
        setSelected({...race, result: loaded.result});
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
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
    setTab('stats');
    try {
      setStats(await Api.stats());
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
          setSelected(null);
          setAnalysis(null);
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
            loading={loading}
            error={error}
            onDay={chooseDay}
            onRefresh={refresh}
          />
        )}
        {tab === 'programme' && (
          <Program
            dayOffset={dayOffset}
            meetings={meetings}
            selections={selections}
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
        {tab === 'stats' && <Stats stats={stats} error={error} />}
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
        onSelections={() => setTab('selections')}
        onProgram={() => setTab('programme')}
        onResults={() => setTab('results')}
        onStats={loadStats}
        onSettings={() => setTab('settings')}
      />
    </SafeAreaView>
  );
}

function SelectionsScreen({
  dayOffset,
  selections,
  loading,
  error,
  onDay,
  onRefresh,
}: {
  dayOffset: 0 | 1;
  selections: any;
  loading: boolean;
  error: string;
  onDay: (offset: 0 | 1) => void;
  onRefresh: () => void;
}) {
  const dayReady = !!selections?.day && (
    !!selections.day.ready ||
    ['horse', 'placed', 'outsider', 'tocard', 'heart'].some(kind => !!selections.day[kind])
  );
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
          Tous les chevaux de la journée comparés par notre méthode indépendante et approfondie.
        </Text>
        <DaySwitcher dayOffset={dayOffset} onDay={onDay} />
        <GoldButton label="Actualiser analyses et résultats" icon="↻" onPress={onRefresh} />
      </View>
      {loading && <Loading text="Comparaison de tous les chevaux…" />}
      {!!error && <ErrorCard title="Connexion interrompue" text={error} />}
      {dayReady ? (
        <DayPicks picks={selections.day} />
      ) : (
        !loading && <EmptyState title="Sélections en attente" text="Actualise les données pour calculer les choix de la journée." />
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
  loading,
  error,
  onDay,
  onRefresh,
  onRace,
}: {
  dayOffset: 0 | 1;
  meetings: Meeting[];
  selections: any;
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
          {!!activeRace && <CourseMenuCard race={activeRace} onOpen={() => onRace(activeRace)} />}
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

function CourseMenuCard({race, onOpen}: {race: Race; onOpen: () => void}) {
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
        <Chip text={race.discipline} />
        <Chip text={`${race.distance_m || '?'} m`} />
        <Chip text={`${race.runners.length} partants`} />
        {!!race.class_name && <Chip text={race.class_name} />}
        {!!race.purse_eur && <Chip text={`${Math.round(race.purse_eur).toLocaleString('fr-FR')} €`} />}
      </View>
      {!!race.result && <Arrival result={race.result} />}
      <GoldButton label="Ouvrir l’analyse complète" icon="→" onPress={onOpen} />
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

function Stats({stats, error}: {stats: any; error: string}) {
  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.pageIntro}>
        <Eyebrow>TRANSPARENCE DU MODÈLE</Eyebrow>
        <Text style={s.pageTitle}>Journal de performance</Text>
        <Text style={s.pageText}>
          Seules les analyses figées avant le départ sont évaluées. Aucun résultat ne peut réécrire
          le passé.
        </Text>
      </View>
      {!!error && <Text style={s.error}>{error}</Text>}
      {!!stats && (
        <View style={s.statsGrid}>
          <Stat label="Courses évaluées" value={stats.races_evaluees} featured />
          <Stat
            label="Choix gagnant"
            value={stats.choix_gagnant_pct != null ? `${stats.choix_gagnant_pct}%` : '—'}
          />
          <Stat
            label="Choix placé Top 3"
            value={stats.choix_place_top3_pct != null ? `${stats.choix_place_top3_pct}%` : '—'}
          />
          <Stat
            label="Gagnant dans Top 3"
            value={
              stats.gagnant_dans_top3_performance_pct != null
                ? `${stats.gagnant_dans_top3_performance_pct}%`
                : '—'
            }
          />
        </View>
      )}
      <View style={s.infoCard}>
        <Eyebrow>PROTOCOLE</Eyebrow>
        <Text style={s.infoTitle}>Mesurer sans réécrire</Text>
        <Text style={s.body}>
          Chaque snapshot conserve les scores tels qu’ils existaient avant le départ. Les résultats
          servent ensuite uniquement à mesurer la précision réelle de la méthode.
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
  const performance = analysis?.scores || [];
  const placed = useMemo(
    () => [...(analysis?.scores || [])].sort((a, b) => b.placed - a.placed),
    [analysis],
  );
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
            <Chip text={race.discipline} />
            <Chip text={`${race.distance_m || '?'} m`} />
            {!!race.going && <Chip text={race.going} />}
            {!!race.start_type && <Chip text={race.start_type} />}
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
            {performance.map((score, index) => (
              <RunnerCard key={score.number} rank={index + 1} score={score} detailed />
            ))}
            <Section
              eyebrow="HIÉRARCHIE PRINCIPALE"
              title="Top 3 — Modèle complet"
              text="La lecture globale orientée performance et possibilité de victoire."
            />
            {performance.slice(0, 3).map((score, index) => (
              <RunnerCard key={`top-${score.number}`} rank={index + 1} score={score} />
            ))}
            <Explanation text={analysis.summary.block_explanations?.performance} color={C.gold} />
            <Section
              eyebrow="SÉCURITÉ"
              title="Top 3 — Simple Placé"
              text="Les profils les plus fiables pour conserver une place malgré plusieurs scénarios."
            />
            {placed.slice(0, 3).map((score, index) => (
              <RunnerCard key={`placed-${score.number}`} rank={index + 1} score={score} placed />
            ))}
            <Explanation text={analysis.summary.block_explanations?.placed} color={C.green} />
            <Synthesis analysis={analysis} />
            <Conclusion analysis={analysis} />
            <View style={s.houseCard}>
              <View style={s.houseHead}>
                <Text style={s.houseMark}>H</Text>
                <View style={{flex: 1}}>
                  <Text style={s.houseKicker}>BLOC INDÉPENDANT</Text>
                  <Text style={s.houseTitle}>Objectif visé par la maison</Text>
                </View>
              </View>
              <Text style={s.houseText}>
                Non déterminé tant que les données officielles ne permettent pas de vérifier
                objectivement la préparation, les changements de pilote, de ferrure, d’équipement et
                les engagements. Ce bloc ne modifie jamais les scores ni les classements.
              </Text>
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function RunnerCard({
  rank,
  score,
  placed = false,
  detailed = false,
}: {
  rank: number;
  score: Score;
  placed?: boolean;
  detailed?: boolean;
}) {
  const paragraph = String(
    score.breakdown?.analysis_text ||
      'Données objectives encore insuffisantes pour rédiger une analyse complète.',
  );
  const history = Array.isArray(score.breakdown?.history)
    ? (score.breakdown.history as Array<Record<string, any>>)
    : [];
  return (
    <View style={[s.runnerCard, rank <= 3 && s.runnerRanked]}>
      <View style={s.runnerTop}>
        <View style={[s.rank, rank === 1 && s.rankFirst]}>
          <Text style={[s.rankText, rank === 1 && s.rankTextFirst]}>{rank}</Text>
        </View>
        <View style={s.numberBox}>
          <Text style={s.numberLabel}>N°</Text>
          <Text style={s.numberValue}>{score.number}</Text>
        </View>
        <View style={{flex: 1}}>
          <Text style={s.runnerName}>{score.horse_name}</Text>
          <Text numberOfLines={2} style={s.runnerReasons}>
            {score.reasons.slice(0, 2).join(' · ') || 'Données encore limitées'}
          </Text>
        </View>
        <View style={s.mainScoreCircle}>
          <Text style={s.mainScore}>{Math.round(placed ? score.placed : score.performance)}</Text>
          <Text style={s.mainScoreUnit}>/100</Text>
        </View>
      </View>
      {!!detailed && (
        <View style={s.paragraph}>
          <View style={s.paragraphLine} />
          <Text style={s.analysisText}>{paragraph}</Text>
        </View>
      )}
      {!!detailed && history.length > 0 && <HistoryRows rows={history} />}
      <View style={s.scoreGrid}>
        <ScoreBadge label="Perf" value={score.performance} color={C.goldBright} />
        <ScoreBadge label="Placé" value={score.placed} color={C.green} />
        <ScoreBadge label="Caché" value={score.hidden_potential} color={C.purple} />
        <ScoreBadge label="Robuste" value={score.robustness} color={C.blue} />
        <ScoreBadge label="Volatilité" value={score.uncertainty} color={C.coral} />
      </View>
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
        const result = row.disqualified ? 'DQ' : row.position != null ? `${row.position}e` : 'NC';
        const context = [
          row.track,
          row.distance_m ? `${row.distance_m} m` : null,
          row.chrono_km_seconds ? `${Number(row.chrono_km_seconds).toFixed(1)} s/km` : null,
          row.going,
        ].filter(Boolean).join(' · ');
        return (
          <View key={`${row.date || 'ligne'}-${index}`} style={s.historyRow}>
            <Text style={s.historyDate}>{String(row.date || '—')}</Text>
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
      <Insight index="04" label="Convergence" value={(analysis.summary.best_convergence || []).join(' – ')} color={C.coral} />
      <Explanation text={analysis.summary.block_explanations?.convergence} color={C.coral} />
      <Insight index="05" label="À ne pas négliger" value={(analysis.summary.do_not_overlook || []).join(' – ') || 'Aucun profil distinct'} color={C.blue} />
      <Explanation text={analysis.summary.block_explanations?.do_not_overlook} color={C.blue} />
      <Insight index="08" label="Sélection élargie" value={(analysis.summary.selection_8 || []).join(' – ')} color={C.muted} />
      <Explanation text={analysis.summary.block_explanations?.selection_8} color={C.muted} />
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
  runnerCard: {backgroundColor: C.card, borderRadius: 21, borderWidth: 1, borderColor: C.lineSoft, padding: 15, gap: 13},
  runnerRanked: {borderColor: '#2F2E29'},
  runnerTop: {flexDirection: 'row', alignItems: 'center', gap: 9},
  rank: {width: 29, height: 29, borderRadius: 15, backgroundColor: C.raised, borderWidth: 1, borderColor: C.line, alignItems: 'center', justifyContent: 'center'},
  rankFirst: {backgroundColor: C.gold, borderColor: C.gold},
  rankText: {color: C.muted, fontWeight: '900', fontSize: 11},
  rankTextFirst: {color: '#17130C'},
  numberBox: {width: 38, height: 44, borderRadius: 11, backgroundColor: '#090C11', alignItems: 'center', justifyContent: 'center'},
  numberLabel: {color: C.mutedDark, fontSize: 7, fontWeight: '900'},
  numberValue: {color: C.ivory, fontSize: 17, fontWeight: '900', marginTop: -1},
  runnerName: {color: C.ivory, fontSize: 15, fontWeight: '900'},
  runnerReasons: {color: C.mutedDark, fontSize: 9.5, lineHeight: 14, marginTop: 3},
  mainScoreCircle: {width: 53, height: 53, borderRadius: 27, borderWidth: 1.5, borderColor: C.goldDeep, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0A0C0F'},
  mainScore: {color: C.goldBright, fontSize: 19, fontWeight: '900', lineHeight: 20},
  mainScoreUnit: {color: C.goldDeep, fontSize: 6.5, fontWeight: '900'},
  paragraph: {flexDirection: 'row', gap: 11, paddingVertical: 2},
  paragraphLine: {width: 2, borderRadius: 1, backgroundColor: C.goldDeep},
  analysisText: {flex: 1, color: '#B2B5BB', lineHeight: 20, fontSize: 12.5},
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
});
