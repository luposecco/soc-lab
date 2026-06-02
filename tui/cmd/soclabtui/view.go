package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

func (m model) View() string {
	base := m.width
	if base <= 0 {
		base = 120
	}

	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	bold110 := lipgloss.NewStyle().Foreground(lipgloss.Color("110")).Bold(true)
	card := lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("67")).Padding(0, 1)

	svcCardW := base / 3
	if base < 90 {
		svcCardW = 28
	}
	if svcCardW < 28 {
		svcCardW = 28
	}
	if svcCardW > 56 {
		svcCardW = 56
	}
	maxStackW := max(28, base-4)
	if svcCardW > maxStackW {
		svcCardW = maxStackW
	}
	svcInnerW := svcCardW - 4
	if svcInnerW < 20 {
		svcInnerW = 20
	}

	svcRows := []string{lipgloss.NewStyle().Foreground(lipgloss.Color("117")).Bold(true).Render("  Services")}
	maxSvcLineW := lipgloss.Width("  · elastalert2    running (healthy)")
	for _, s := range m.services {
		statePreview := s.State
		if s.Health != "" {
			statePreview += " (" + s.Health + ")"
		}
		if w := lipgloss.Width(fmt.Sprintf("  · %-14s %s", s.Name, statePreview)); w > maxSvcLineW {
			maxSvcLineW = w
		}
	}
	desiredSvcW := maxSvcLineW + 4
	if desiredSvcW > svcCardW && desiredSvcW <= max(28, base-52) {
		svcCardW = desiredSvcW
		svcInnerW = svcCardW - 4
	}
	if len(m.services) == 0 {
		svcRows = append(svcRows, "  · no data")
	}
	for _, s := range m.services {
		stateStyle := dim
		healthStyle := dim
		if strings.EqualFold(s.State, "running") {
			stateStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("114")).Bold(true)
		} else if strings.EqualFold(s.State, "exited") || strings.EqualFold(s.State, "dead") {
			stateStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("203")).Bold(true)
		}
		if strings.EqualFold(s.Health, "healthy") {
			healthStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("114"))
		} else if s.Health != "" {
			healthStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("221"))
		}
		state := stateStyle.Render(s.State)
		if s.Health != "" {
			state += " " + healthStyle.Render("("+s.Health+")")
		}
		line := fmt.Sprintf("  · %-14s %s", s.Name, state)
		if lipgloss.Width(line) > svcInnerW {
			svcRows = append(svcRows, fmt.Sprintf("  · %s", s.Name), fmt.Sprintf("    %s", state))
		} else {
			svcRows = append(svcRows, line)
		}
	}

	// pad to a fixed minimum (5 slots) so panel height stays stable when stack is stopped
	const minSvcSlots = 5
	filled := len(m.services)
	if filled == 0 {
		filled = 1 // "no data" line counts as one slot
	}
	for filled < minSvcSlots {
		svcRows = append(svcRows, "")
		filled++
	}

	svcRows = append(svcRows, "")
	dotColor := lipgloss.Color("245")
	switch m.es.ClusterHealth {
	case "green":
		dotColor = lipgloss.Color("114")
	case "yellow":
		dotColor = lipgloss.Color("67")
	case "red":
		dotColor = lipgloss.Color("203")
	}
	dot := lipgloss.NewStyle().Foreground(dotColor).Render("●")
	healthLabel := func() string {
		switch m.es.ClusterHealth {
		case "green":
			return lipgloss.NewStyle().Foreground(lipgloss.Color("114")).Render("green")
		case "yellow":
			return lipgloss.NewStyle().Foreground(lipgloss.Color("67")).Render("yellow")
		case "red":
			return lipgloss.NewStyle().Foreground(lipgloss.Color("203")).Render("red")
		default:
			return dim.Render("n/a")
		}
	}()
	svcRows = append(svcRows,
		fmt.Sprintf("  ES  %s %s", dot, healthLabel),
		fmt.Sprintf("  %s %-8s  %s %s", dim.Render("events"), bold110.Render(formatCount(m.es.EventCount)), dim.Render("alerts"), bold110.Render(formatCount(m.es.AlertCount))),
		fmt.Sprintf("  %s %s", dim.Render("updated"), dim.Render("live")),
	)

	rulesStateStyle := func(status string) string {
		switch strings.ToLower(status) {
		case "ok":
			return lipgloss.NewStyle().Foreground(lipgloss.Color("114")).Bold(true).Render("ok")
		case "fail":
			return lipgloss.NewStyle().Foreground(lipgloss.Color("203")).Bold(true).Render("fail")
		default:
			return dim.Render("n/a")
		}
	}
	ruleRows := []string{lipgloss.NewStyle().Foreground(lipgloss.Color("117")).Bold(true).Render("  Rules Status")}
	ruleRows = append(ruleRows,
		fmt.Sprintf("  suricata: %s  (ET:%d custom:%d)", rulesStateStyle(m.rules.Suricata.Status), m.rules.Suricata.ETRules, m.rules.Suricata.CustomRules),
		fmt.Sprintf("  sigma:    %s  (loaded:%d fail:%d)", rulesStateStyle(m.rules.Sigma.Status), m.rules.Sigma.LoadedRules, m.rules.Sigma.FailCount),
	)
	if strings.EqualFold(m.rules.Suricata.Status, "fail") {
		ruleRows = append(ruleRows, fmt.Sprintf("  log: %s", dim.Render(m.rules.Suricata.ErrorLog)))
	} else if strings.EqualFold(m.rules.Sigma.Status, "fail") {
		ruleRows = append(ruleRows, fmt.Sprintf("  log: %s", dim.Render(m.rules.Sigma.ErrorLog)))
	}
	ruleRows = append(ruleRows, fmt.Sprintf("  %s %s", dim.Render("rules"), dim.Render(m.rules.UpdatedAt)))

	// always 4 content rows for stable height
	captureRows := []string{
		lipgloss.NewStyle().Foreground(lipgloss.Color("117")).Bold(true).Render("  Capture"),
	}
	if m.capture.LiveActive {
		dot := lipgloss.NewStyle().Foreground(lipgloss.Color("114")).Render("●")
		iface := m.capture.Interface
		if iface == "" {
			iface = "?"
		}
		captureRows = append(captureRows,
			fmt.Sprintf("  · live    %s active  %s", dot, dim.Render(iface)),
		)
		if m.capture.ChunksTotal > 0 {
			captureRows = append(captureRows,
				fmt.Sprintf("  · chunks  %s / %s played",
					bold110.Render(fmt.Sprintf("%d", m.capture.ChunksTotal)),
					dim.Render(fmt.Sprintf("%d", m.capture.ChunksPlayed)),
				),
			)
		} else {
			captureRows = append(captureRows, "")
		}
		if m.capture.LastChunkAge > 0 {
			age := m.capture.LastChunkAge
			var ageStr string
			switch {
			case age < time.Minute:
				ageStr = fmt.Sprintf("%ds ago", int(age.Seconds()))
			case age < time.Hour:
				ageStr = fmt.Sprintf("%dm ago", int(age.Minutes()))
			default:
				ageStr = fmt.Sprintf("%dh ago", int(age.Hours()))
			}
			captureRows = append(captureRows, fmt.Sprintf("  · latest  %s", dim.Render(ageStr)))
		} else {
			captureRows = append(captureRows, "")
		}
	} else {
		dot := lipgloss.NewStyle().Foreground(lipgloss.Color("245")).Render("○")
		captureRows = append(captureRows,
			fmt.Sprintf("  · live    %s idle", dot),
			"",
			"",
		)
	}
	capturePanel := card.Width(svcCardW).Render(strings.Join(captureRows, "\n"))

	svcPanel := card.Width(svcCardW).Render(strings.Join(svcRows, "\n"))
	rulesPanel := card.Width(svcCardW).Render(strings.Join(ruleRows, "\n"))
	svcH := lipgloss.Height(svcPanel)
	svcW := lipgloss.Width(svcPanel)
	rightPanels := lipgloss.JoinVertical(lipgloss.Left, svcPanel, rulesPanel, capturePanel)
	rightW := lipgloss.Width(rightPanels)
	if base >= svcW*2+24 {
		maxSideW := max(28, (base-6)/2)
		if svcCardW > maxSideW {
			svcCardW = maxSideW
			svcInnerW = svcCardW - 4
			svcPanel = card.Width(svcCardW).Render(strings.Join(svcRows, "\n"))
			rulesPanel = card.Width(svcCardW).Render(strings.Join(ruleRows, "\n"))
			capturePanel = card.Width(svcCardW).Render(strings.Join(captureRows, "\n"))
			svcH = lipgloss.Height(svcPanel)
		}
		rightPanels = lipgloss.JoinVertical(lipgloss.Left, lipgloss.JoinHorizontal(lipgloss.Top, svcPanel, rulesPanel), capturePanel)
		rightW = lipgloss.Width(rightPanels)
	}

	banner := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("110")).Render(
		fitBanner(base, []string{
			"  ███████╗ ██████╗  ██████╗      ██╗      █████╗ ██████╗",
			"  ██╔════╝██╔═══██╗██╔════╝      ██║     ██╔══██╗██╔══██╗",
			"  ███████╗██║   ██║██║      ███╗ ██║     ███████║██████╔╝",
			"  ╚════██║██║   ██║██║      ╚══╝ ██║     ██╔══██║██╔══██╗",
			"  ███████║╚██████╔╝╚██████╗      ███████╗██║  ██║██████╔╝",
			"  ╚══════╝ ╚═════╝  ╚═════╝      ╚══════╝╚═╝  ╚═╝╚═════╝",
		}),
	)
	helper := m.helperLine()
	sub := lipgloss.NewStyle().Foreground(lipgloss.Color("240")).Render("  " + helper)
	leftContent := lipgloss.JoinVertical(lipgloss.Left, banner, "", sub)
	bannerW := lipgloss.Width(banner)
	if base < rightW+max(48, bannerW) {
		rightPanels = lipgloss.JoinVertical(lipgloss.Left, svcPanel, rulesPanel, capturePanel)
		rightW = lipgloss.Width(rightPanels)
	}
	leftWidth := base - rightW
	if leftWidth < 1 {
		leftWidth = 1
	}
	minSideBySide := rightW + max(48, bannerW)
	tooNarrow := base < minSideBySide
	leftH := lipgloss.Height(leftContent)
	// Lines the top section may occupy while still leaving ≥5 lines for output.
	// Fixed cost: rule(1) + activity(1) + inputBox(3) + outputFixed(4) + minVP(5) = 14
	availForTop := m.height - 14

	callsign := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("110")).Render("  SOC LAB")

	var top string
	switch {
	case m.focusMode:
		top = leftContent // placeholder; sections assembly skips it in focus mode

	case availForTop <= 0:
		top = "" // terminal too short for anything above the bars

	case availForTop < 3:
		top = callsign

	case availForTop < leftH:
		top = callsign + "\n\n" + dim.Render("  tab  ↑↓ history  f: focus  q: quit")

	case tooNarrow && base >= 60 && availForTop >= 24:
		// Wrap layout: banner full-width, all panels below in two columns
		// (services left | rules+capture stacked right)
		half := max(24, (base-8)/2)
		svcLeft := card.Width(half).Render(strings.Join(svcRows, "\n"))
		rulesRight := card.Width(half).Render(strings.Join(ruleRows, "\n"))
		captureRight := card.Width(half).Render(strings.Join(captureRows, "\n"))
		belowPanels := lipgloss.JoinHorizontal(lipgloss.Top,
			svcLeft,
			lipgloss.JoinVertical(lipgloss.Left, rulesRight, captureRight),
		)
		top = lipgloss.JoinVertical(lipgloss.Left, leftContent, belowPanels)

	case !tooNarrow && availForTop >= 24:
		// Side-by-side layout (wide terminal, tall enough for panels)
		panelH := max(max(svcH, lipgloss.Height(rulesPanel)), leftH)
		leftCol := lipgloss.Place(leftWidth, panelH, lipgloss.Left, lipgloss.Center, leftContent)
		rightCol := lipgloss.Place(rightW, panelH, lipgloss.Left, lipgloss.Center, rightPanels)
		top = lipgloss.JoinHorizontal(lipgloss.Top, leftCol, rightCol)

	default:
		// Banner only: tall enough for the banner but not for panels
		top = leftContent
	}

	topH := 0
	if top != "" && !m.focusMode {
		topH = lipgloss.Height(top)
	}
	vpW := max(1, base-4)
	m.viewport.Width = vpW

	// build completion overlay — styled to match the TUI theme, paints over bottom of output box
	const maxCompShow = 7
	var completionOverlay []string
	if len(m.completions) > 0 {
		sepStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("67")).Background(lipgloss.Color("235"))
		rowStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("245")).Background(lipgloss.Color("235"))
		selStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("110")).Background(lipgloss.Color("237")).Bold(true)
		sep := sepStyle.Width(vpW).Render(strings.Repeat("─", vpW))
		completionOverlay = append(completionOverlay, sep)
		shown := m.completions
		if len(shown) > maxCompShow {
			shown = shown[:maxCompShow]
		}
		for i, c := range shown {
			if i == m.completionIdx {
				completionOverlay = append(completionOverlay, selStyle.Width(vpW).Render("  ❯ "+c))
			} else {
				completionOverlay = append(completionOverlay, rowStyle.Width(vpW).Render("    "+c))
			}
		}
	}

	rule := lipgloss.NewStyle().Foreground(lipgloss.Color("238")).Render(strings.Repeat("─", base))
	activity := m.activityBar(base)
	input := m.input.View()
	if len(m.completions) == 0 {
		if s := m.suggestion(); s != "" {
			tail := strings.TrimPrefix(s, m.input.Value())
			input = m.input.Prompt + m.input.Value() + dim.Render(tail)
		}
	}
	if m.running {
		input = "running command..."
	}
	inputBox := card.Width(base - 2).Render(input)
	inputH := lipgloss.Height(inputBox)
	// outputBlock = vpH (viewport) + 2 (cmdHeader+blank inside) + 2 (borders) = vpH+4
	// sections: [top, rule(1), activity(1), outputBlock(vpH+4), inputBox] — no compH in overhead
	overhead := topH + 1 + 1 + inputH + 4
	vpH := m.height - overhead
	if vpH < 1 {
		vpH = 1
	}
	m.viewport.Height = vpH
	cmd := strings.TrimSpace(m.lastCmd)
	if cmd == "" {
		cmd = "-"
	}
	cmdHeader := lipgloss.NewStyle().Foreground(lipgloss.Color("117")).Render("$ " + cmd)

	// overlay completions over the last N lines of viewport output
	rawVP := m.styleOutput(m.viewport.View())
	vpLines := strings.Split(rawVP, "\n")
	if len(completionOverlay) > 0 {
		n := len(completionOverlay)
		start := len(vpLines) - n
		if start < 0 {
			start = 0
		}
		for i, cl := range completionOverlay {
			if start+i < len(vpLines) {
				vpLines[start+i] = cl
			}
		}
	}

	outputContent := cmdHeader + "\n\n" + strings.Join(vpLines, "\n")
	outputBlock := lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("238")).Padding(0, 1).Render(outputContent)

	sections := []string{rule, activity}
	if !m.focusMode && top != "" {
		sections = append([]string{top}, sections...)
	}
	sections = append(sections, outputBlock, inputBox)
	return strings.Join(sections, "\n")
}
