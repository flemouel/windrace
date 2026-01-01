<?php
// Affichage de l'état du vent
$wind_speed = 5.4 + (rand(0, 30) / 10);
$winners = rand(0, 5);
$total_played = 842423 + rand(1, 100);

echo "﻿<div id='ocean-wave' class='wave" . rand(1, 5) . "'></div>";
echo "<div id='ocean-water'>";
echo "<p><b>Wind instrument online (simulated)</b></p>";
echo "<p>Wind speed " . number_format($wind_speed, 1) . "kn<br/>";
echo "Winners in last hour: {$winners}/" . ($winners + rand(1, 3)) . "<br/>";
echo "Totally played {$total_played} times</p>";
echo "</div>";
?>
